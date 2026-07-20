import json
import re
import secrets
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
from courses.marking import blank_matches
from courses.marking import normalize_text
from courses.marking import parse_number
from courses.sanitize import sanitize_cell
from courses.sanitize import sanitize_html
from courses.sanitize import sanitize_label
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
    "slidebreakelement",
    "tableelement",
    "galleryelement",
    "tabselement",
    "revealgateelement",
    "fillgateelement",
    "switchgateelement",
    "spoilerelement",
    "switchgridelement",
    "filltableelement",
    "calloutelement",
    "choicegridquestionelement",
    "stepperelement",
    "multigridquestionelement",
    "twocolumnelement",
    "markdoneelement",
    "guessnumberelement",
]


class Element(models.Model):
    """GFK join-row: an ordered slot in a unit pointing at one concrete element.

    A row with `parent` set is a child of a TabsElement's join row, living in the
    tab named by `tab_id`. Children KEEP their `unit` FK, which is what lets
    Course.delete / ContentNode.delete sweep them up unchanged. `order` is compared
    only within a (unit, parent, tab_id) group, so groups may reuse integers.
    """

    unit = models.ForeignKey(
        ContentNode,
        on_delete=models.CASCADE,
        related_name="elements",
        limit_choices_to={"kind": "unit"},
    )
    title = models.CharField(max_length=200, blank=True)  # optional author label
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children",
    )
    tab_id = models.CharField(max_length=12, blank=True, default="")
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

    def _state_context(self, element, state, slug, node_pk):
        """{el, eid, mine, mine_json, slug, node_pk} -- the leaf contract.

        `mine_json` is json.dumps(mine), for a leaf to emit as data-state. Serialized
        HERE, in Python: there is no JSON filter in this project, and `{{ mine }}` would
        render Python's repr ({'open': True}), which JSON.parse rejects.

        Every leaf gets it whether or not it reads one -- the gate is the only consumer
        today. A leaf that hand-builds its own render_to_string context instead of
        splatting this (the Table/Gallery pattern) forfeits it silently.

        NOT `checked`: mark-done-only, added by ElementBase.render below.

        `eid == 0` means "a content object with no join row" (transient/mid-create),
        NOT "editor preview" -- the preview passes REAL join rows and is made inert
        by its context lacking slug/node_pk (so `{% url ... as save_url %}` -> "").
        """
        eid = element.pk if element is not None else 0
        mine = (state or {}).get(eid)
        if not isinstance(mine, dict):
            mine = {}  # read-side fail-open: drifted blob -> render fresh, never 500
        return {
            "el": self,
            "eid": eid,
            "mine": mine,
            "mine_json": json.dumps(mine),
            "slug": slug,
            "node_pk": node_pk,
        }

    def render(self, *, element=None, state=None, slug=None, node_pk=None):
        name = self._meta.model_name
        ctx = self._state_context(element, state, slug, node_pk)
        raw = ctx["mine"].get("items", ())
        if not isinstance(raw, (list, tuple)):
            raw = ()
        checked = set()
        for x in raw:
            try:
                checked.add(int(x))
            except (TypeError, ValueError):
                continue
        return render_to_string(
            f"courses/elements/{name}.html", {**ctx, "checked": checked}
        )


class TextElement(ElementBase):
    body = models.TextField(blank=True)
    elements = GenericRelation(Element)  # cascade: deleting this removes its join-row

    def save(self, *args, **kwargs):
        self.body = sanitize_html(self.body)
        super().save(*args, **kwargs)


class SpoilerElement(ElementBase):
    """A self-contained show/hide disclosure: an author-labelled button that
    expands/collapses a block of rich text + math. Rendered as a native
    <details>; two-way, repeatable, ungraded. See the spoiler-element design doc."""

    label = models.CharField(max_length=120, blank=True)
    body = models.TextField(blank=True)
    elements = GenericRelation(Element)  # cascade: deleting this removes its join-row

    def save(self, *args, **kwargs):
        self.body = sanitize_html(self.body)
        super().save(*args, **kwargs)


class CalloutElement(ElementBase):
    """A framed, always-visible callout/aside (Example/Note/Tip/Warning) holding
    rich text + math. Zero JS, no server endpoint. Mirrors SpoilerElement minus the
    toggle, plus a `kind` and an optional heading. See the callout-element design
    doc."""

    class Kind(models.TextChoices):
        EXAMPLE = "example", _("Example")
        NOTE = "note", _("Note")
        TIP = "tip", _("Tip")
        WARNING = "warning", _("Warning")

    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.EXAMPLE)
    heading = models.CharField(max_length=120, blank=True)
    body = models.TextField(blank=True)
    elements = GenericRelation(Element)  # cascade: deleting this removes its join-row

    def save(self, *args, **kwargs):
        if self.kind not in self.Kind.values:
            self.kind = self.Kind.EXAMPLE
        self.body = sanitize_html(self.body)
        super().save(*args, **kwargs)

    @property
    def display_heading(self):
        # String fallback key ("example"), NOT bare `Kind.EXAMPLE` — `Kind` is a nested
        # class and would resolve against module globals (undefined -> NameError).
        return self.heading or KIND_DEFAULT_HEADING.get(
            self.kind, KIND_DEFAULT_HEADING["example"]
        )


# Defined AFTER the class so it can read the choice labels; keyed by value string.
# `.label` is the lazy translation string, so this stays translation-safe.
KIND_DEFAULT_HEADING = {k.value: k.label for k in CalloutElement.Kind}


class StepperElement(ElementBase):
    """Step-by-step: an ordered list of short inline fragments (text + \\(...\\)
    math) shown on one wrapping line. The first is visible; a walking "Show next"
    button reveals the rest one at a time. Ungraded and lesson-only, but the
    revealed step depth persists per-student in UnitProgress.element_state -- keyed
    by the Element JOIN-ROW pk (not this object's pk), blob {"shown": N} -- via the
    courses:element_state_save endpoint. See the stepper design doc."""

    MIN_STEPS = 1
    MAX_STEPS = 20
    MAX_LEN = 500

    prompt = models.CharField(max_length=MAX_LEN, blank=True)  # optional lead-in
    elements = GenericRelation(Element)  # cascade: deleting this removes its join-row

    def save(self, *args, **kwargs):
        self.prompt = (self.prompt or "").strip()
        super().save(*args, **kwargs)


class StepperStep(models.Model):
    stepper = models.ForeignKey(
        StepperElement, on_delete=models.CASCADE, related_name="steps"
    )
    content = models.CharField(max_length=StepperElement.MAX_LEN)  # plain text + KaTeX
    order = OrderField(for_fields=["stepper"], blank=True)

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return self.content

    def save(self, *args, **kwargs):
        self.content = (self.content or "").strip()
        super().save(*args, **kwargs)


class MarkDoneElement(ElementBase):
    """Self-tracking checklist: an optional prompt + an ordered list of short
    statement items the student ticks to record "I've done this". Ungraded,
    lesson-only, nestable. Ticks persist per-student in
    UnitProgress.element_state, keyed by the ELEMENT JOIN-ROW pk (not this
    object's pk), under {"items": [MarkDoneItem.pk, ...]}."""

    MIN_ITEMS = 1
    MAX_ITEMS = 20
    MAX_LEN = 500

    prompt = models.CharField(max_length=MAX_LEN, blank=True)
    elements = GenericRelation(Element)  # cascade join-row cleanup

    def save(self, *args, **kwargs):
        self.prompt = (self.prompt or "").strip()
        super().save(*args, **kwargs)


class MarkDoneItem(models.Model):
    element = models.ForeignKey(
        MarkDoneElement, on_delete=models.CASCADE, related_name="items"
    )
    content = models.CharField(max_length=MarkDoneElement.MAX_LEN)  # plain text + KaTeX
    order = OrderField(for_fields=["element"], blank=True)

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return self.content

    def save(self, *args, **kwargs):
        self.content = (self.content or "").strip()
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
    # SHA-256 hex of the file bytes; used by the LAL import loader for durable
    # (course, content_hash) dedup. Blank on assets created before/without hashing.
    content_hash = models.CharField(
        max_length=64, blank=True, default="", db_index=True
    )
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

    def render(self, unit, course, theme=None):
        from django.conf import settings

        from courses import htmlsandbox

        doc = htmlsandbox.build_srcdoc(
            self.html,
            course.html_css,
            course.html_js,
            unit.html_seed_js,
            origin=settings.HTMLEL_SANDBOX_ORIGIN,
            theme=theme,
        )
        return render_to_string("courses/elements/htmlelement.html", {"doc": doc})


class SlideBreakElement(ElementBase):
    """Field-less delimiter: splits a unit's elements into slides (slideshow mode).

    Rendered content is nothing — the taking view consumes breaks in
    partition_into_slides. A defensive empty template exists only so a generic
    .render() path (builder preview) cannot 500 on a missing template."""

    elements = GenericRelation(Element)  # cascade: deleting this removes its join-row


class RevealGateElement(ElementBase):
    """A 'Show more' gate: a thin divider that (client-side) hides the
    following sibling elements until its button is clicked. See the
    reveal-gate design doc."""

    label = models.CharField(max_length=120, blank=True)

    elements = GenericRelation(Element)


class FillGateElement(ElementBase):
    """A 'Fill in & confirm' gate: a reveal gate whose trigger is a fill-in blank.
    A correct (server-checked) answer reveals the following siblings. Records no
    marks. `stem` is the ￿n￿ token-stem (from fillblank.parse); `answers` is the
    parsed accepted-alternatives list (list[list[str]]). See the design doc."""

    stem = models.TextField(blank=True)
    answers = models.JSONField(default=list)
    elements = GenericRelation(Element)  # cascade: deleting this removes its join-row

    @property
    def canonical_answers(self):
        """First accepted alternative per blank -- the canonical spelling shown,
        locked, on restore of a correctly-answered gate. `answers` is
        list[list[str]]; a blank with no alternatives renders empty."""
        return [(a[0] if a else "") for a in (self.answers or [])]

    def render(self, *, element=None, state=None, slug=None, node_pk=None):
        from django.template.loader import render_to_string

        ctx = self._state_context(element, state, slug, node_pk)
        return render_to_string("courses/elements/fillgateelement.html", ctx)


class SwitchGateElement(ElementBase):
    """A 'Choose & confirm' gate: a reveal gate whose trigger is an inline cycling
    'Choose ▾' widget. A correct (server-checked) choice reveals the following
    siblings. Records no marks. `stem` holds the ￿0￿ single-token stem (the cycler
    position); `options` is the sanitized list[str] of choice HTML fragments;
    `answer` is the 0-based index of the correct option. See the design doc."""

    stem = models.TextField(blank=True)
    options = models.JSONField(default=list)
    answer = models.IntegerField(default=0)
    elements = GenericRelation(Element)  # cascade: deleting this removes its join-row

    def save(self, *args, **kwargs):
        self.options = [sanitize_cell(o or "") for o in (self.options or [])]
        super().save(*args, **kwargs)

    def render(self, *, element=None, state=None, slug=None, node_pk=None):
        from django.template.loader import render_to_string

        ctx = self._state_context(element, state, slug, node_pk)
        return render_to_string("courses/elements/switchgateelement.html", ctx)


class GuessNumberElement(ElementBase):
    """A numeric self-check with directional feedback: a wrong guess is told
    'too big' or 'too small' and can be retried without limit. Records no marks
    and reveals nothing (NOT a reveal gate) — it exists to be got wrong
    repeatedly, which is why it is not a QuestionElement. `stem` holds the
    U+FFFF 0 U+FFFF single-token stem (the input position); `target` is lifted
    out of the token by the form. See the design doc."""

    stem = models.TextField(blank=True)
    target = models.DecimalField(max_digits=20, decimal_places=8)
    tolerance = models.DecimalField(
        max_digits=20, decimal_places=8, default=0, validators=[MinValueValidator(0)]
    )
    success_message = models.TextField(blank=True)
    elements = GenericRelation(Element)  # cascade: deleting this removes its join-row

    @property
    def canonical_target(self):
        """Display-formatted target, reusing courses.guessnumber.format_target() --
        NEVER a fresh Decimal.normalize() (that alone yields E-notation for round
        numbers, e.g. 40401 -> '4.0401E+4', the exact defect format_target's own
        docstring records already fixing once). Shown, readonly, on restore of a
        correctly-answered guess: the student's exact within-tolerance guess is
        not stored (monotone blob), so the canonical target is what is shown."""
        from courses.guessnumber import format_target

        return format_target(self.target)

    def save(self, *args, **kwargs):
        # success_message only: `stem` is sanitised form-side, in order
        # (sanitize_html -> strip_sentinel -> parse), so save() must not touch it.
        self.success_message = sanitize_html(self.success_message or "")
        super().save(*args, **kwargs)

    def render(self, *, element=None, state=None, slug=None, node_pk=None):
        from django.template.loader import render_to_string

        ctx = self._state_context(element, state, slug, node_pk)
        return render_to_string("courses/elements/guessnumberelement.html", ctx)


class SwitchGridElement(ElementBase):
    """A 'Switch grid' self-check: multiple lines interleaving static math with
    clickable cyclers, graded as a whole grid with per-cycler feedback. Records no
    marks and reveals nothing (NOT a reveal gate). `prompt` is a plain-text
    instruction line; `lines` is a list of {stem, cyclers} where stem is the token
    stem (the sentinel-marked token stem, one sentinel per cycler) and each cycler
    is {options: list[str], answer: int}."""

    prompt = models.TextField(blank=True)
    lines = models.JSONField(default=list)
    elements = GenericRelation(Element)  # cascade: deleting this removes its join-row

    def save(self, *args, **kwargs):
        for line in self.lines or []:
            for cyc in line.get("cyclers", []) or []:
                cyc["options"] = [
                    sanitize_cell(o or "") for o in (cyc.get("options") or [])
                ]
        super().save(*args, **kwargs)

    def render(self, *, element=None, state=None, slug=None, node_pk=None):
        from django.template.loader import render_to_string

        ctx = self._state_context(element, state, slug, node_pk)
        return render_to_string("courses/elements/switchgridelement.html", ctx)


class TableElement(ElementBase):
    """Styled table: a JSON grid of {html, halign, valign} cells plus header
    toggles and a border preset. Cell html is sanitised at save()."""

    DEFAULT_BORDER = "grid"
    BORDERS = {"grid", "rows", "header", "none"}
    HALIGN = {"left", "center", "right"}
    VALIGN = {"top", "middle", "bottom"}
    MAX_ROWS = 50
    MAX_COLS = 20

    data = models.JSONField(default=dict)
    elements = GenericRelation(Element)

    @staticmethod
    def _cell(raw):
        raw = raw if isinstance(raw, dict) else {}
        h = raw.get("halign")
        v = raw.get("valign")
        return {
            "html": raw.get("html") or "",
            "halign": h if h in TableElement.HALIGN else "left",
            "valign": v if v in TableElement.VALIGN else "top",
        }

    @staticmethod
    def normalize_data(data):
        """Return a well-formed dict for arbitrary stored data: defaults for
        missing top-level keys; ragged rows rectangularised (padded, never
        truncated); non-list rows / non-dict cells coerced; and a
        degenerate-collapse guard to the default 2x2 when height or width is 0."""
        data = data if isinstance(data, dict) else {}
        rows = data.get("cells")
        rows = rows if isinstance(rows, list) else []
        rows = [r if isinstance(r, list) else [] for r in rows]
        width = max((len(r) for r in rows), default=0)
        if not rows or width == 0:
            rows = [[{}, {}], [{}, {}]]  # default 2x2
            width = 2
        cells = [
            [TableElement._cell(r[i] if i < len(r) else {}) for i in range(width)]
            for r in rows
        ]
        border = data.get("border")
        return {
            "header_row": bool(data.get("header_row")),
            "header_col": bool(data.get("header_col")),
            "border": border
            if border in TableElement.BORDERS
            else TableElement.DEFAULT_BORDER,
            "cells": cells,
        }

    def save(self, *args, **kwargs):
        self.data = self._sanitized_data(self.data)
        super().save(*args, **kwargs)

    @staticmethod
    def _sanitized_data(data):
        """Sanitise every cell's html in place, reading defensively so a
        malformed legacy shape cannot raise. The real write paths (form, import)
        normalise first; this is defense-in-depth for all paths."""
        if not isinstance(data, dict):
            return data
        rows = data.get("cells")
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, list):
                    continue
                for cell in row:
                    if isinstance(cell, dict):
                        cell["html"] = sanitize_cell(cell.get("html", ""))
        return data

    def render(self, *, element=None, state=None, slug=None, node_pk=None):
        from django.template.loader import render_to_string

        data = self.normalize_data(self.data)
        return render_to_string(
            "courses/elements/tableelement.html", {"el": self, "data": data}
        )

    @property
    def normalized_data(self):
        return self.normalize_data(self.data)


class FillTableElement(ElementBase):
    """Ungraded self-check table: a JSON grid whose cells are either static
    (rich HTML/math, sanitised at save) or answer cells (a plain accepted-answer
    string). Checked server-side per cell; records no marks, reveals nothing."""

    ANSWER = "answer"
    STATIC = "static"
    # Reuse TableElement's structural caps (TableElement is defined just above).
    MAX_ROWS = TableElement.MAX_ROWS
    MAX_COLS = TableElement.MAX_COLS

    data = models.JSONField(default=dict)
    elements = GenericRelation(Element)

    @staticmethod
    def _cell(raw):
        raw = raw if isinstance(raw, dict) else {}
        h = raw.get("halign")
        v = raw.get("valign")
        halign = h if h in TableElement.HALIGN else "left"
        valign = v if v in TableElement.VALIGN else "top"
        if raw.get("kind") == FillTableElement.ANSWER:
            ans = raw.get("answer")
            return {
                "kind": FillTableElement.ANSWER,
                "answer": ans if isinstance(ans, str) else "",
                "halign": halign,
                "valign": valign,
            }
        return {
            "kind": FillTableElement.STATIC,
            "html": raw.get("html") or "",
            "halign": halign,
            "valign": valign,
        }

    @staticmethod
    def normalize_data(data):
        data = data if isinstance(data, dict) else {}
        rows = data.get("cells")
        rows = rows if isinstance(rows, list) else []
        rows = [r if isinstance(r, list) else [] for r in rows]
        width = max((len(r) for r in rows), default=0)
        if not rows or width == 0:
            rows = [[{}, {}], [{}, {}]]  # default 2x2
            width = 2
        cells = [
            [FillTableElement._cell(r[i] if i < len(r) else {}) for i in range(width)]
            for r in rows
        ]
        border = data.get("border")
        prompt = data.get("prompt")
        return {
            "header_row": bool(data.get("header_row")),
            "header_col": bool(data.get("header_col")),
            "case_sensitive": bool(data.get("case_sensitive")),
            "border": border
            if border in TableElement.BORDERS
            else TableElement.DEFAULT_BORDER,
            "prompt": prompt.strip() if isinstance(prompt, str) else "",
            "cells": cells,
        }

    @property
    def canonical_cells(self):
        """Grid shaped exactly like normalize_data(self.data)["cells"]: static
        cells pass through unchanged; each answer cell's `answer` is replaced by
        its FIRST pipe-delimited alternative (courses.filltable.split_alternatives
        ()[0]; no configured alternatives -> ""). Restore-only (mine.done); reads
        self.data via normalize_data() but NEVER mutates it -- normalize_data()
        already returns fresh cell dicts, not references into self.data."""
        from courses.filltable import split_alternatives

        cells = self.normalize_data(self.data)["cells"]
        out = []
        for row in cells:
            out_row = []
            for cell in row:
                if cell.get("kind") == self.ANSWER:
                    alts = split_alternatives(cell.get("answer", ""))
                    out_row.append({**cell, "answer": alts[0] if alts else ""})
                else:
                    out_row.append(cell)
            out.append(out_row)
        return out

    @staticmethod
    def _sanitized_data(data):
        """Sanitise static-cell html and trim answer strings, in place, defensively."""
        if not isinstance(data, dict):
            return data
        p = data.get("prompt")
        data["prompt"] = p.strip() if isinstance(p, str) else ""
        rows = data.get("cells")
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, list):
                    continue
                for cell in row:
                    if not isinstance(cell, dict):
                        continue
                    if cell.get("kind") == FillTableElement.ANSWER:
                        a = cell.get("answer")
                        cell["answer"] = a.strip() if isinstance(a, str) else ""
                    else:
                        cell["html"] = sanitize_cell(cell.get("html", ""))
        return data

    def save(self, *args, **kwargs):
        self.data = self._sanitized_data(self.data)
        super().save(*args, **kwargs)

    def render(self, *, element=None, state=None, slug=None, node_pk=None):
        from django.template.loader import render_to_string

        ctx = self._state_context(element, state, slug, node_pk)
        if ctx["mine"].get("done"):
            # Shallow-copied dict, NEVER `self.data["cells"] = ...` -- mutating
            # self.data in place would silently overwrite the student's stored
            # pipe-delimited alternatives in-memory for the rest of the request.
            ctx["data"] = {
                **self.normalize_data(self.data),
                "cells": self.canonical_cells,
            }
        else:
            ctx["data"] = self.normalize_data(self.data)
        return render_to_string("courses/elements/filltableelement.html", ctx)

    @property
    def normalized_data(self):
        return self.normalize_data(self.data)


class GalleryElement(ElementBase):
    """Image carousel: an ordered list of course-image references, each with an
    optional rich-text + math description. Descriptions are sanitised at save()."""

    CAPTION_POSITIONS = {"above", "below"}
    DEFAULT_POS = "below"
    MIN_IMAGES = 2
    MAX_IMAGES = 20

    data = models.JSONField(default=dict)
    elements = GenericRelation(Element)

    @staticmethod
    def _image(raw):
        if not isinstance(raw, dict):
            return None
        media = raw.get("media")
        if not isinstance(media, int) or isinstance(media, bool):
            return None
        desc = raw.get("desc")
        return {"media": media, "desc": desc if isinstance(desc, str) else ""}

    @staticmethod
    def normalize_data(data):
        """Well-formed dict for arbitrary stored data; never raises. Drops any
        image entry without a valid int `media`. Duplicates are preserved."""
        data = data if isinstance(data, dict) else {}
        raw = data.get("images")
        raw = raw if isinstance(raw, list) else []
        images = [img for img in (GalleryElement._image(r) for r in raw) if img]
        pos = data.get("desc_pos")
        return {
            "desc_pos": pos
            if pos in GalleryElement.CAPTION_POSITIONS
            else GalleryElement.DEFAULT_POS,
            "images": images,
        }

    def save(self, *args, **kwargs):
        self.data = self._sanitized_data(self.data)
        super().save(*args, **kwargs)

    @staticmethod
    def _sanitized_data(data):
        """Normalise first (so hostile shapes can't raise), then sanitise every
        description. Defense-in-depth on all write paths (form, import, admin)."""
        norm = GalleryElement.normalize_data(data)
        for img in norm["images"]:
            img["desc"] = sanitize_cell(img.get("desc", ""))
        return norm

    def resolved_images(self):
        """Ordered [{media: MediaAsset, desc: str}] for image ids that still
        resolve; unresolved ids are skipped (never 500s a lesson page)."""
        norm = self.normalize_data(self.data)
        ids = [img["media"] for img in norm["images"]]
        assets = MediaAsset.objects.in_bulk(ids)  # {pk: MediaAsset}
        out = []
        for img in norm["images"]:
            asset = assets.get(img["media"])
            if asset is not None:
                out.append({"media": asset, "desc": img["desc"]})
        return out

    @property
    def normalized_data(self):
        return self.normalize_data(self.data)

    def render(self, *, element=None, state=None, slug=None, node_pk=None):
        from django.template.loader import render_to_string
        from django.utils.translation import gettext as _t

        from courses.sanitize import desc_to_alt

        norm = self.normalize_data(self.data)
        resolved = self.resolved_images()
        total = len(resolved)
        figures = []
        for i, img in enumerate(resolved, start=1):
            alt = desc_to_alt(img["desc"])
            if not alt and img["desc"]:
                # non-empty but strips to empty (math-only) -> generic alt
                alt = _t("Image {n} of {total}").format(n=i, total=total)
            figures.append(
                {"url": img["media"].file.url, "desc": img["desc"], "alt": alt}
            )
        if not figures:
            return ""  # 0 resolvable images -> render nothing
        return render_to_string(
            "courses/elements/galleryelement.html",
            {"el": self, "desc_pos": norm["desc_pos"], "figures": figures},
        )


class TabsElement(ElementBase):
    """Tabbed container: holds ONLY the tab labels + stable ids. The children live
    in Element rows whose `parent` points at this element's join row.

    Two normalizers, deliberately separate:
      * normalize_labels_and_ids -- non-destructive; called by save(); persisted.
      * normalize_data           -- destructive (pads/truncates); read-side only.
    save() must NEVER call normalize_data: padding/truncation changes WHICH tabs
    exist, and persisting that would permanently orphan a tab's children.
    """

    MIN_TABS = 2
    MAX_TABS = 10
    LABEL_MAX = 80
    TAB_ID_RE = re.compile(r"t[0-9a-f]{6}")

    data = models.JSONField(default=dict)
    elements = GenericRelation(Element)

    @staticmethod
    def new_tab_id(taken=()):
        """'t' + 6 lowercase hex (7 chars, fits tab_id's max_length=12). Unique
        only WITHIN one element, so collision is checked against `taken`."""
        while True:
            tid = "t" + secrets.token_hex(3)
            if tid not in taken:
                return tid

    @staticmethod
    def default_data():
        """The two empty tabs a freshly-added tabs element is born with. Labels are
        stored untranslated (they are stored data, not UI copy; translating at write
        time would freeze them to the author's locale)."""
        first = TabsElement.new_tab_id()
        second = TabsElement.new_tab_id({first})
        return {
            "tabs": [
                {"id": first, "label": "Tab 1"},
                {"id": second, "label": "Tab 2"},
            ]
        }

    @staticmethod
    def normalize_labels_and_ids(data):
        """NON-DESTRUCTIVE. Never changes which tabs exist, so it can never orphan a
        child by removing its tab. Fills blank labels, strips/truncates them, mints
        missing ids, and regenerates the LATER of a duplicate pair (the first keeps
        its id). Never raises."""
        data = data if isinstance(data, dict) else {}
        raw = data.get("tabs")
        raw = raw if isinstance(raw, list) else []
        tabs, taken = [], set()
        for i, item in enumerate(raw, start=1):
            item = item if isinstance(item, dict) else {}
            label = item.get("label")
            label = sanitize_label(
                label if isinstance(label, str) else "", TabsElement.LABEL_MAX
            )
            if not label:
                label = f"Tab {i}"
            tid = item.get("id")
            if (
                not isinstance(tid, str)
                or not TabsElement.TAB_ID_RE.fullmatch(tid)
                or tid in taken
            ):
                tid = TabsElement.new_tab_id(taken)
            taken.add(tid)
            tabs.append({"id": tid, "label": label})
        return {"tabs": tabs}

    @staticmethod
    def normalize_data(data):
        """DESTRUCTIVE (pads to MIN_TABS, truncates to MAX_TABS). READ-SIDE ONLY --
        called by resolved_tabs() when rendering a damaged blob, never persisted.
        Never raises. A blob can only become out-of-bounds via a direct DB edit: the
        form enforces the bounds on every authored write and import rejects them."""
        norm = TabsElement.normalize_labels_and_ids(data)
        tabs = norm["tabs"][: TabsElement.MAX_TABS]
        taken = {t["id"] for t in tabs}
        while len(tabs) < TabsElement.MIN_TABS:
            tid = TabsElement.new_tab_id(taken)
            taken.add(tid)
            tabs.append({"id": tid, "label": f"Tab {len(tabs) + 1}"})
        return {"tabs": tabs}

    def save(self, *args, **kwargs):
        self.data = self.normalize_labels_and_ids(self.data)
        super().save(*args, **kwargs)

    @property
    def normalized_data(self):
        return self.normalize_data(self.data)

    def join_row(self):
        """This concrete's single Element join row (the GFK is effectively 1:1).
        The ONE handle every children-consumer uses: render(), resolved_tabs(),
        has_math, and the export walk. order_by('pk') is defensive determinism."""
        return self.elements.order_by("pk").first()

    def resolved_tabs(self):
        """Ordered [(tab_dict, [child Element join rows])], grouped by tab_id and
        ordered by `order` within each group. EVERY tab is emitted, including empty
        ones -- a new tabs element has two empty tabs, and skipping them would erase
        them from the strip the enhancer builds. Children whose tab_id resolves to no
        tab (direct DB edit, read-side truncation) are skipped, never raised on."""
        tabs = self.normalize_data(self.data)["tabs"]
        join = self.join_row()
        if join is None:  # transient, mid-create
            return [(tab, []) for tab in tabs]
        by_tab = {}
        children = (
            join.children.order_by("order", "pk")
            .select_related("content_type")
            .prefetch_related("content_object")
        )
        for child in children:
            by_tab.setdefault(child.tab_id, []).append(child)
        return [(tab, by_tab.get(tab["id"], [])) for tab in tabs]

    def render(self, *, element=None, state=None, slug=None, node_pk=None):
        from django.template.loader import render_to_string

        return render_to_string(
            "courses/elements/tabselement.html",
            {
                "el": self,
                "tabs": self.resolved_tabs(),
                "eid": element.pk if element is not None else 0,
                "element_state": state,
                "slug": slug,
                "node_pk": node_pk,
            },
        )


class TwoColumnElement(ElementBase):
    """Layout container: holds ONLY the ordered column ids. Children live in Element
    rows whose `parent` points at this element's join row and whose `tab_id` is the
    column id. Two normalizers, deliberately separate (mirrors TabsElement):
      * normalize_ids   -- NON-destructive; called by save(); persisted.
      * normalize_data  -- DESTRUCTIVE (pads/truncates to 2..4); read-side only.
    save() must NEVER call normalize_data -- it mints phantom ids and orphans children.
    """

    MIN_COLUMNS = 2
    MAX_COLUMNS = 4
    COLUMN_ID_RE = re.compile(r"c[0-9a-f]{6}")

    data = models.JSONField(default=dict)
    elements = GenericRelation(Element)

    @staticmethod
    def new_column_id(taken=()):
        """'c' + 6 lowercase hex (7 chars, fits tab_id's max_length=12)."""
        while True:
            cid = "c" + secrets.token_hex(3)
            if cid not in taken:
                return cid

    @staticmethod
    def default_data():
        """The two empty columns a freshly-added two-column element is born with."""
        first = TwoColumnElement.new_column_id()
        second = TwoColumnElement.new_column_id({first})
        return {"columns": [{"id": first}, {"id": second}]}

    @staticmethod
    def normalize_ids(data):
        """NON-DESTRUCTIVE. Never changes which columns exist; mints a fresh id for any
        entry whose id is missing, malformed, or a duplicate (first of a dup pair kept).
        Never raises."""
        data = data if isinstance(data, dict) else {}
        raw = data.get("columns")
        raw = raw if isinstance(raw, list) else []
        columns, taken = [], set()
        for item in raw:
            item = item if isinstance(item, dict) else {}
            cid = item.get("id")
            if (
                not isinstance(cid, str)
                or not TwoColumnElement.COLUMN_ID_RE.fullmatch(cid)
                or cid in taken
            ):
                cid = TwoColumnElement.new_column_id(taken)
            taken.add(cid)
            columns.append({"id": cid})
        return {"columns": columns}

    @staticmethod
    def normalize_data(data):
        """DESTRUCTIVE (pads to MIN_COLUMNS, truncates to MAX_COLUMNS). READ-SIDE
        ONLY -- called by resolved_columns() when rendering, never persisted."""
        norm = TwoColumnElement.normalize_ids(data)
        columns = norm["columns"][: TwoColumnElement.MAX_COLUMNS]
        taken = {c["id"] for c in columns}
        while len(columns) < TwoColumnElement.MIN_COLUMNS:
            cid = TwoColumnElement.new_column_id(taken)
            taken.add(cid)
            columns.append({"id": cid})
        return {"columns": columns}

    def save(self, *args, **kwargs):
        self.data = self.normalize_ids(self.data)
        super().save(*args, **kwargs)

    def join_row(self):
        """This concrete's single Element join row (the GFK is effectively 1:1)."""
        return self.elements.order_by("pk").first()

    def resolved_columns(self):
        """Ordered [(column_dict, [child Element join rows])], grouped by tab_id and
        ordered by `order`. EVERY column emitted (including empty). Enumerates columns
        via the DESTRUCTIVE read-side normalize_data (the 2..4 render clamp)."""
        columns = self.normalize_data(self.data)["columns"]
        join = self.join_row()
        if join is None:  # transient, mid-create
            return [(col, []) for col in columns]
        by_col = {}
        children = (
            join.children.order_by("order", "pk")
            .select_related("content_type")
            .prefetch_related("content_object")
        )
        for child in children:
            by_col.setdefault(child.tab_id, []).append(child)
        return [(col, by_col.get(col["id"], [])) for col in columns]

    def render(self, *, element=None, state=None, slug=None, node_pk=None):
        from django.template.loader import render_to_string

        return render_to_string(
            "courses/elements/twocolumnelement.html",
            {
                "el": self,
                "columns": self.resolved_columns(),
                "eid": element.pk if element is not None else 0,
                "element_state": state,
                "slug": slug,
                "node_pk": node_pk,
            },
        )


class QuestionElement(ElementBase):
    """Abstract base for all question element types (Phase 2).

    Owns the shared rich-text fields and declares the marking contract. Concrete
    subclasses implement mark(); the server is the sole marking authority.
    """

    # Practice-state (slice 3): does a lesson-mode answer to this type persist and
    # restore across reload? Base default off; the five simple, server-refillable
    # types opt in. Single source of truth for BOTH the save (check_answer) and the
    # restore (render_element) sides.
    RESTORABLE_IN_LESSON = False

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

    RESTORABLE_IN_LESSON = True

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
        # `answer` is an already-validated set of this question's choice ids.
        # Single source of choices for both the correct-set and the annotated-set
        # (one query; choices are prefetched on the quiz/results builders).
        choices = list(self.choices.all())
        correct_set = frozenset(c.pk for c in choices if c.is_correct)
        is_correct = set(answer) == set(correct_set)
        # annotated = options whose selection state is WRONG (selected XOR correct)
        # and that carry feedback. Covers BOTH a selected distractor AND a missed
        # correct option (the symmetric difference answer △ correct). A fully-correct
        # answer yields an empty symmetric difference, so no explicit is_correct guard
        # is needed; dropping it is what enables the omission case (a wrong answer with
        # only missed-correct options still annotates).
        annotated = frozenset(
            c.pk for c in choices if c.feedback and ((c.pk in answer) != c.is_correct)
        )
        return MarkResult(
            correct=is_correct,
            fraction=1.0 if is_correct else 0.0,
            reveal=correct_set,
            annotated=annotated,
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
                # Lesson: per-option feedback renders INLINE in the choices list, so
                # the bottom reveal list is suppressed (this override only — the base
                # QuestionElement.render must keep REVEAL_TEMPLATE for other types'
                # no-JS path).
                "reveal_template": None if mode == "lesson" else self.REVEAL_TEMPLATE,
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
    feedback = models.CharField(max_length=500, blank=True, default="")
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

    RESTORABLE_IN_LESSON = True

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

    RESTORABLE_IN_LESSON = True

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

    RESTORABLE_IN_LESSON = True

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

    RESTORABLE_IN_LESSON = True

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
            ok = blank_matches(vals[i], lines, case_sensitive=blank.case_sensitive)
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

    RESTORABLE_IN_LESSON = True

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

    RESTORABLE_IN_LESSON = True

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


class ChoiceGridQuestionElement(QuestionElement):
    """Matrix single-choice: N statements each answered by one of a shared set of
    columns. Partial credit per row. Mirrors MatchPairQuestionElement's relational
    shape but with two children (columns + rows)."""

    RESTORABLE_IN_LESSON = True

    REVEAL_TEMPLATE = "courses/elements/_reveal_choicegrid.html"
    elements = GenericRelation(Element)

    def delete(self, *args, **kwargs):
        # GridRow.correct_column PROTECTs GridColumn. Both rows and columns are
        # CASCADE children of this question, but Django's collector can gather a
        # column before the row that protects it and then raise ProtectedError.
        # Deleting the rows first drops those PROTECT references so the question's
        # own cascade can remove the (now unreferenced) columns cleanly.
        self.rows.all().delete()
        return super().delete(*args, **kwargs)

    def build_answer(self, post):
        rows = list(self.rows.all())
        valid = {c.pk for c in self.columns.all()}
        out = []
        for row in rows:
            raw = post.get(f"row_{row.pk}")
            try:
                pk = int(raw)
            except (TypeError, ValueError):
                pk = None
            out.append(pk if pk in valid else "")
        return out

    def mark(self, answer):
        rows = list(self.rows.all())
        n = len(rows)
        answer = (list(answer) + [""] * n)[:n]  # pad/truncate; guards answer drift
        label_map = {c.pk: c.label for c in self.columns.all()}
        reveal = []
        n_correct = 0
        for i, row in enumerate(rows):
            chosen = answer[i]
            is_correct = chosen == row.correct_column_id
            if is_correct:
                n_correct += 1
            reveal.append(
                {
                    "statement": row.statement,
                    "correct_label": label_map.get(row.correct_column_id),
                    "chosen_label": label_map.get(chosen) if chosen != "" else None,
                    "is_correct": is_correct,
                }
            )
        return MarkResult(
            correct=(n_correct == n and n > 0),
            fraction=(n_correct / n) if n else 0.0,
            reveal=tuple(reveal),
        )


class GridColumn(models.Model):
    question = models.ForeignKey(
        ChoiceGridQuestionElement, on_delete=models.CASCADE, related_name="columns"
    )
    label = models.CharField(max_length=500)  # plain text + KaTeX; never sanitised
    order = OrderField(for_fields=["question"], blank=True)

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return self.label


class GridRow(models.Model):
    question = models.ForeignKey(
        ChoiceGridQuestionElement, on_delete=models.CASCADE, related_name="rows"
    )
    statement = models.CharField(max_length=500)  # plain text + KaTeX
    correct_column = models.ForeignKey(
        GridColumn, on_delete=models.PROTECT, related_name="+"
    )
    order = OrderField(for_fields=["question"], blank=True)

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return self.statement


class MultiGridQuestionElement(QuestionElement):
    """Multi-select grid: N statements each answered by a *set* of columns.
    All-or-nothing per row, grid-level partial credit. Sibling of
    ChoiceGridQuestionElement, but a row owns a ManyToMany set of correct
    columns instead of a single FK."""

    RESTORABLE_IN_LESSON = True

    REVEAL_TEMPLATE = "courses/elements/_reveal_multigrid.html"
    elements = GenericRelation(Element)

    def build_answer(self, post):
        rows = list(self.rows.all())
        valid = {c.pk for c in self.columns.all()}
        out = []
        for row in rows:
            chosen = set()
            for raw in post.getlist(f"row_{row.pk}"):
                try:
                    pk = int(raw)
                except (TypeError, ValueError):
                    continue
                if pk in valid:
                    chosen.add(pk)
            out.append(sorted(chosen))
        return out

    def mark(self, answer):
        rows = list(self.rows.all())
        n = len(rows)
        answer = (list(answer) + [[]] * n)[:n]  # pad/truncate; guards length drift
        cols = list(self.columns.all())  # column order for deterministic reveal
        reveal = []
        n_correct = 0
        for i, row in enumerate(rows):
            entry = answer[i]
            chosen = set(entry) if isinstance(entry, (list, tuple)) else set()
            correct = {c.pk for c in row.correct_columns.all()}
            is_correct = chosen == correct
            if is_correct:
                n_correct += 1
            reveal.append(
                {
                    "statement": row.statement,
                    "correct_labels": [c.label for c in cols if c.pk in correct],
                    "chosen_labels": [c.label for c in cols if c.pk in chosen],
                    "is_correct": is_correct,
                }
            )
        return MarkResult(
            correct=(n_correct == n and n > 0),
            fraction=(n_correct / n) if n else 0.0,
            reveal=tuple(reveal),
        )


class MultiGridColumn(models.Model):
    question = models.ForeignKey(
        MultiGridQuestionElement, on_delete=models.CASCADE, related_name="columns"
    )
    label = models.CharField(max_length=500)  # plain text + KaTeX; never sanitised
    order = OrderField(for_fields=["question"], blank=True)

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return self.label


class MultiGridRow(models.Model):
    question = models.ForeignKey(
        MultiGridQuestionElement, on_delete=models.CASCADE, related_name="rows"
    )
    statement = models.CharField(max_length=500)  # plain text + KaTeX
    # Set of correct columns. M2M (not a FK): deleting a column simply drops it
    # from every row's set (no PROTECT dance). related_name="+" (no reverse needed).
    correct_columns = models.ManyToManyField(MultiGridColumn, related_name="+")
    order = OrderField(for_fields=["question"], blank=True)

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return self.statement


ZONE_COORD_EPSILON = 1e-6


class DragToImageQuestionElement(QuestionElement):
    """Drag labels onto author-defined rectangle zones over an image. Marking is
    per-zone via the shared DnD substrate; each zone's correct token is a DragZone
    row. `stem` (inherited) is the optional prompt above the image."""

    RESTORABLE_IN_LESSON = True

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
    # Per-student practice state, keyed by Element (join-row) pk:
    # {"<Element.pk>": {...per-type blob}}. Personal, ungraded, invisible to
    # analytics. Reset (progress_reset) clears this and nothing else.
    element_state = models.JSONField(default=dict)
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
