"""Forms for creating and editing the per-type lesson and question content elements."""

from django import forms
from django.forms import inlineformset_factory
from django.utils.translation import gettext_lazy as _

from courses import fillblank
from courses.embed import extract_embed_url
from courses.embed import parse_iframe_dimensions
from courses.marking import parse_number
from courses.models import Choice
from courses.models import ChoiceQuestionElement
from courses.models import DragFillBlankQuestionElement
from courses.models import DragToImageQuestionElement
from courses.models import DragZone
from courses.models import ExtendedResponseQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import HtmlElement
from courses.models import IframeElement
from courses.models import ImageElement
from courses.models import MatchPair
from courses.models import MatchPairQuestionElement
from courses.models import MathElement
from courses.models import MediaAsset
from courses.models import QuestionElement
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from courses.models import TextElement
from courses.models import VideoElement
from courses.sanitize import sanitize_html
from courses.video_url import canonicalize_video_url
from courses.widgets import CodeTextarea


class _MarkingFieldsMixin:
    """Make the three marking fields optional in the form.

    All three fields have model-level defaults, so when they are omitted from
    POST (e.g. non-quiz forms where the fields are hidden) Django's
    construct_instance skips setting them and the model defaults apply on save.
    Zero-rejection for max_marks is enforced by the model's MinValueValidator
    via ModelForm._post_clean(); no custom clean methods are needed."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in ("marking_mode", "max_attempts", "max_marks"):
            if field_name in self.fields:
                self.fields[field_name].required = False
                self.fields[field_name].widget.attrs["class"] = "input"


class MediaAssetForm(forms.ModelForm):
    class Meta:
        model = MediaAsset
        fields = ["kind", "file"]

    # No clean() override: presence is checked here, content (extension/size by kind)
    # is validated once by MediaAsset.clean() via create_asset's full_clean() — the
    # single authority. media_upload catches that ValidationError as a 422.


class _CourseScopedMediaForm(forms.ModelForm):
    """Shared base: forms that reference a MediaAsset re-validate course + kind."""

    media_kind = None  # "image" | "video"

    def __init__(self, *args, course=None, **kwargs):
        self.course = course
        super().__init__(*args, **kwargs)
        if "media" in self.fields and course is not None:
            self.fields["media"].queryset = MediaAsset.objects.filter(
                course=course, kind=self.media_kind
            )


class TextElementForm(forms.ModelForm):
    class Meta:
        model = TextElement
        fields = ["body"]


class ImageElementForm(_CourseScopedMediaForm):
    media_kind = "image"

    class Meta:
        model = ImageElement
        fields = ["media", "alt", "figcaption"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["media"].required = True


class VideoElementForm(_CourseScopedMediaForm):
    media_kind = "video"

    # Override the model's URLField as free-text so the raw pasted value
    # (scheme-less, with tracking params, etc.) reaches clean_url intact;
    # canonicalize_video_url is the single parser, and its normalized output is
    # re-validated by validate_embed_url via VideoElement.clean() in _post_clean.
    # Mirrors the IframeElementForm precedent. required=False so an empty paste
    # (valid when a media file is used) is not a required-field error.
    url = forms.CharField(required=False)

    class Meta:
        model = VideoElement
        fields = ["url", "media"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["url"].required = False
        self.fields["media"].required = False

    def clean_url(self):
        return canonicalize_video_url(self.cleaned_data.get("url", ""))

    def _post_clean(self):
        # ModelForm._post_clean() runs instance.full_clean() (→ VideoElement.clean():
        # the url/media XOR + the embed allow-list) AFTER field cleaning. When
        # clean_url already rejected the paste with a precise message, skip that
        # model validation so the XOR doesn't stack a spurious non-field __all__
        # error on top. Otherwise run it normally — it's the single place the XOR +
        # allow-list fire (do NOT also call instance.clean() by hand; that would
        # double the message).
        if "url" in self.errors:
            return
        super()._post_clean()


class IframeElementForm(forms.ModelForm):
    # Override the model's URLField as a free-text field so a pasted "<iframe …>"
    # snippet survives form-field validation; extract_embed_url does the real work
    # and returns the validated https src, which the model's URLField + the
    # validate_embed_url model validator then accept on save.
    url = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3, "data-embed-input": ""}),
        label="URL or embed code",
    )

    class Meta:
        model = IframeElement
        fields = ["url", "title"]

    def clean_url(self):
        raw = self.cleaned_data.get("url", "")
        url = extract_embed_url(raw)
        width, height = parse_iframe_dimensions(raw)
        # Capture only a usable pair (a full <iframe> with numeric width & height);
        # a plain-URL / dimensionless input leaves stored dims unchanged so a
        # title-only edit never wipes a captured ratio. width/height are not form
        # fields, so full_clean excludes them — the ceiling is enforced in
        # parse_iframe_dimensions, not here.
        if width and height:
            self.instance.width = width
            self.instance.height = height
        return url


class MathElementForm(forms.ModelForm):
    class Meta:
        model = MathElement
        fields = ["latex"]


class HtmlElementForm(forms.ModelForm):
    class Meta:
        model = HtmlElement
        fields = ["html"]
        widgets = {"html": CodeTextarea(attrs={"rows": 12})}

    # No clean_html: the raw markup is stored verbatim (sandbox is the boundary).


class ChoiceQuestionElementForm(_MarkingFieldsMixin, forms.ModelForm):
    class Meta:
        model = ChoiceQuestionElement
        fields = [
            "stem",
            "explanation",
            "multiple",
            "marking_mode",
            "max_attempts",
            "max_marks",
        ]
        widgets = {
            "stem": forms.Textarea(attrs={"rows": 3, "data-rte-source": ""}),
            "explanation": forms.Textarea(attrs={"rows": 2, "data-rte-source": ""}),
            "multiple": forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # `multiple` is fixed at creation by the add-card and pinned on edit: drop it
        # from an edit form so a tampered hidden POST value cannot flip single<->multi.
        if self.instance.pk is not None:
            self.fields.pop("multiple", None)


class BaseChoiceFormSet(forms.BaseInlineFormSet):
    """Single source of truth for the choice-count rules (counts only non-deleted,
    non-empty rows; min_num/validate_min are NOT used — they miscount DELETE/empty
    extra rows). `self.multiple` is injected by build_choice_formset."""

    multiple = False

    def clean(self):
        super().clean()
        if any(self.errors):
            # intentional: a per-row field error already blocks the save, so the
            # count/correctness rules below are skipped until rows are individually
            # valid
            return
        kept = [
            f
            for f in self.forms
            if f.cleaned_data
            and not f.cleaned_data.get("DELETE")
            and f.cleaned_data.get("text")
        ]
        if len(kept) < 2:
            raise forms.ValidationError(_("Add at least two choices."))
        correct = [f for f in kept if f.cleaned_data.get("is_correct")]
        if not correct:
            raise forms.ValidationError(_("Mark at least one choice correct."))
        if not self.multiple and len(correct) != 1:
            raise forms.ValidationError(
                _("A single-choice question needs exactly one correct choice.")
            )


ChoiceFormSet = inlineformset_factory(
    ChoiceQuestionElement,
    Choice,
    formset=BaseChoiceFormSet,
    fields=["text", "is_correct"],
    extra=2,
    can_delete=True,
)


def build_choice_formset(
    *, data=None, files=None, instance=None, multiple=None, prefix="choices"
):
    """Construct the Choice inline formset with the multiple-aware clean() rule.
    Shared by the render-only and save paths so validation cannot drift. When
    `multiple` is not passed, derive it from a saved instance (the edit path uses the
    stored value); a brand-new/unsaved instance defaults to single (False)."""
    if multiple is None:
        multiple = (
            bool(instance.multiple) if (instance is not None and instance.pk) else False
        )
    fs = ChoiceFormSet(data=data, files=files, instance=instance, prefix=prefix)
    fs.multiple = multiple
    return fs


class ShortTextQuestionElementForm(_MarkingFieldsMixin, forms.ModelForm):
    class Meta:
        model = ShortTextQuestionElement
        fields = [
            "stem",
            "explanation",
            "accepted",
            "case_sensitive",
            "marking_mode",
            "max_attempts",
            "max_marks",
        ]
        widgets = {
            "stem": forms.Textarea(attrs={"rows": 3, "data-rte-source": ""}),
            "explanation": forms.Textarea(attrs={"rows": 2, "data-rte-source": ""}),
            "accepted": forms.Textarea(attrs={"rows": 3}),
        }

    def clean_accepted(self):
        value = self.cleaned_data.get("accepted", "")
        if not [ln for ln in value.splitlines() if ln.strip()]:
            raise forms.ValidationError(_("Add at least one accepted answer."))
        return value


class ShortNumericQuestionElementForm(_MarkingFieldsMixin, forms.ModelForm):
    class Meta:
        model = ShortNumericQuestionElement
        fields = [
            "stem",
            "explanation",
            "value",
            "tolerance",
            "marking_mode",
            "max_attempts",
            "max_marks",
        ]
        widgets = {
            "stem": forms.Textarea(attrs={"rows": 3, "data-rte-source": ""}),
            "explanation": forms.Textarea(attrs={"rows": 2, "data-rte-source": ""}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Replace the locale-sensitive DecimalField parsing with parse_number so
        # authors get the same ','/'.'  leniency as students (PL/EN bilingual).
        self.fields["value"] = forms.CharField()
        self.fields["tolerance"] = forms.CharField(required=False)

    def _num(self, field, *, required):
        raw = self.cleaned_data.get(field, "")
        if not raw and not required:
            return None
        parsed = parse_number(raw)
        if parsed is None:
            raise forms.ValidationError(_("Enter a number (e.g. 3.14 or 3,14)."))
        return parsed

    def clean_value(self):
        return self._num("value", required=True)

    def clean_tolerance(self):
        parsed = self._num("tolerance", required=False)
        if parsed is None:
            return 0
        if parsed < 0:
            raise forms.ValidationError(_("Tolerance cannot be negative."))
        return parsed


class FillBlankQuestionElementForm(_MarkingFieldsMixin, forms.ModelForm):
    parsed_blanks = None  # list[list[str]] after a successful clean()

    class Meta:
        model = FillBlankQuestionElement
        fields = ["stem", "explanation", "marking_mode", "max_attempts", "max_marks"]
        widgets = {
            "stem": forms.Textarea(attrs={"rows": 3, "data-rte-source": ""}),
            "explanation": forms.Textarea(attrs={"rows": 2, "data-rte-source": ""}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Editing an existing question: show the author's {{answer}} markup, not the
        # stored ￿n￿ token-stem (rebuilt from each Blank's newline-delimited answers).
        if self.instance and self.instance.pk:
            blanks = [
                [p for p in b.accepted.split("\n") if p]
                for b in self.instance.blanks.all()
            ]
            self.initial["stem"] = fillblank.to_author_stem(self.instance.stem, blanks)

    def clean_stem(self):
        raw = self.cleaned_data.get("stem", "")
        clean = fillblank.strip_sentinel(sanitize_html(raw))
        try:
            token_stem, blanks = fillblank.parse(clean)
        except fillblank.FillBlankError:
            raise forms.ValidationError(
                _("Mark at least one blank with {{answer}} (use | for alternatives).")
            ) from None
        self.parsed_blanks = blanks
        return token_stem


class DragFillBlankQuestionElementForm(_MarkingFieldsMixin, forms.ModelForm):
    parsed_dragblanks = None  # list[str] (one token per gap) after a successful clean()

    class Meta:
        model = DragFillBlankQuestionElement
        fields = [
            "stem",
            "distractors",
            "explanation",
            "marking_mode",
            "max_attempts",
            "max_marks",
        ]
        widgets = {
            "stem": forms.Textarea(attrs={"rows": 3, "data-rte-source": ""}),
            "distractors": forms.Textarea(attrs={"rows": 2}),
            "explanation": forms.Textarea(attrs={"rows": 2, "data-rte-source": ""}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Editing an existing question: show the author's {{token}} markup, not the
        # stored ￿n￿ token-stem (each gap holds exactly one token).
        if self.instance and self.instance.pk:
            blanks = [[b.correct_token] for b in self.instance.dragblanks.all()]
            self.initial["stem"] = fillblank.to_author_stem(self.instance.stem, blanks)

    def clean_stem(self):
        raw = self.cleaned_data.get("stem", "")
        clean = fillblank.strip_sentinel(sanitize_html(raw))
        try:
            token_stem, blanks = fillblank.parse(clean)
        except fillblank.FillBlankError:
            raise forms.ValidationError(
                _("Mark at least one gap with {{token}}.")
            ) from None
        tokens = []
        for pieces in blanks:
            if len(pieces) != 1:
                raise forms.ValidationError(
                    _(
                        "Each gap holds one token — use a single answer per {{…}}, "
                        "not alternatives."
                    )
                )
            if len(pieces[0]) > 500:
                raise forms.ValidationError(
                    _("A token is too long (max 500 characters).")
                )
            tokens.append(pieces[0])
        self.parsed_dragblanks = tokens
        return token_stem


class MatchPairQuestionElementForm(_MarkingFieldsMixin, forms.ModelForm):
    class Meta:
        model = MatchPairQuestionElement
        fields = [
            "stem",
            "distractors",
            "explanation",
            "marking_mode",
            "max_attempts",
            "max_marks",
        ]
        widgets = {
            "stem": forms.Textarea(attrs={"rows": 2, "data-rte-source": ""}),
            "distractors": forms.Textarea(attrs={"rows": 2}),
            "explanation": forms.Textarea(attrs={"rows": 2, "data-rte-source": ""}),
        }


class BaseMatchPairFormSet(forms.BaseInlineFormSet):
    """At least one non-deleted, fully-filled pair (left AND right). Mirrors
    BaseChoiceFormSet: min_num/validate_min are NOT used (they miscount DELETE/empty
    extra rows)."""

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        kept = [
            f
            for f in self.forms
            if f.cleaned_data
            and not f.cleaned_data.get("DELETE")
            and f.cleaned_data.get("left")
            and f.cleaned_data.get("right")
        ]
        if len(kept) < 1:
            raise forms.ValidationError(_("Add at least one pair."))


MatchPairFormSet = inlineformset_factory(
    MatchPairQuestionElement,
    MatchPair,
    formset=BaseMatchPairFormSet,
    fields=["left", "right"],
    extra=2,
    can_delete=True,
)


def build_matchpair_formset(*, data=None, files=None, instance=None, prefix="pairs"):
    """Construct the MatchPair inline formset. Shared by the render-only and save paths
    so validation cannot drift (mirror of build_choice_formset)."""
    return MatchPairFormSet(data=data, files=files, instance=instance, prefix=prefix)


class DragToImageQuestionElementForm(_MarkingFieldsMixin, _CourseScopedMediaForm):
    media_kind = "image"

    class Meta:
        model = DragToImageQuestionElement
        # stem + explanation included (mirroring MatchPairQuestionElementForm) — the
        # spec calls stem "the optional prompt above the image", the render template
        # prints el.stem, and _question_has_math scans it. Omitting them would make
        # an unauthored, dead feature. (The spec §6 field list was incomplete here.)
        fields = [
            "stem",
            "media",
            "alt",
            "distractors",
            "explanation",
            "marking_mode",
            "max_attempts",
            "max_marks",
        ]
        widgets = {
            "stem": forms.Textarea(attrs={"rows": 2, "data-rte-source": ""}),
            "distractors": forms.Textarea(attrs={"rows": 2}),
            "explanation": forms.Textarea(attrs={"rows": 2, "data-rte-source": ""}),
        }

    def __init__(self, *args, **kwargs):
        # MRO: _MarkingFieldsMixin -> _CourseScopedMediaForm (strips course kwarg)
        super().__init__(*args, **kwargs)
        self.fields["media"].required = True


class BaseDragZoneFormSet(forms.BaseInlineFormSet):
    """At least one non-deleted, fully-filled zone. Mirrors BaseMatchPairFormSet:
    min_num/validate_min are NOT used (they miscount DELETE/empty extra rows)."""

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        kept = [
            f
            for f in self.forms
            if f.cleaned_data
            and not f.cleaned_data.get("DELETE")
            and f.cleaned_data.get("correct_label")
        ]
        if len(kept) < 1:
            raise forms.ValidationError(_("Add at least one zone."))


DragZoneFormSet = inlineformset_factory(
    DragToImageQuestionElement,
    DragZone,
    formset=BaseDragZoneFormSet,
    fields=["correct_label", "x", "y", "w", "h", "order"],
    widgets={
        "correct_label": forms.TextInput(
            attrs={"placeholder": _("Label for this zone")}
        ),
    },
    extra=0,
    can_delete=True,
)


def build_dragzone_formset(*, data=None, files=None, instance=None, prefix="zones"):
    """Construct the DragZone inline formset (mirror of build_matchpair_formset)."""
    return DragZoneFormSet(data=data, files=files, instance=instance, prefix=prefix)


class ExtendedResponseQuestionElementForm(_MarkingFieldsMixin, forms.ModelForm):
    class Meta:
        model = ExtendedResponseQuestionElement
        fields = [
            "stem",
            "explanation",
            "required_keywords",
            "forbidden_keywords",
            "marking_mode",
            "max_attempts",
            "max_marks",
        ]
        widgets = {
            "stem": forms.Textarea(attrs={"rows": 3, "data-rte-source": ""}),
            "explanation": forms.Textarea(attrs={"rows": 2, "data-rte-source": ""}),
            "required_keywords": forms.Textarea(attrs={"rows": 3}),
            "forbidden_keywords": forms.Textarea(attrs={"rows": 3}),
        }

    def clean(self):
        cleaned = super().clean()
        # Effective mode: _MarkingFieldsMixin makes marking_mode optional and the
        # lesson/hidden-field path omits it from POST, so an absent value means the
        # model default (AUTO) applies on save — validate against that.
        mode = cleaned.get("marking_mode") or QuestionElement.MarkingMode.AUTO
        if mode == QuestionElement.MarkingMode.AUTO:
            req = [
                ln
                for ln in (cleaned.get("required_keywords") or "").splitlines()
                if ln.strip()
            ]
            forb = [
                ln
                for ln in (cleaned.get("forbidden_keywords") or "").splitlines()
                if ln.strip()
            ]
            if not req and not forb:
                raise forms.ValidationError(
                    _(
                        "Auto-marked extended response needs at least one"
                        " required or forbidden keyword."
                    )
                )
        return cleaned


FORM_FOR_TYPE = {
    "text": TextElementForm,
    "image": ImageElementForm,
    "video": VideoElementForm,
    "iframe": IframeElementForm,
    "math": MathElementForm,
    "html": HtmlElementForm,
    "choicequestion": ChoiceQuestionElementForm,
    "shorttextquestion": ShortTextQuestionElementForm,
    "shortnumericquestion": ShortNumericQuestionElementForm,
    "fillblankquestion": FillBlankQuestionElementForm,
    "dragfillblankquestion": DragFillBlankQuestionElementForm,
    "matchpairquestion": MatchPairQuestionElementForm,
    "dragtoimagequestion": DragToImageQuestionElementForm,
    "extendedresponsequestion": ExtendedResponseQuestionElementForm,
}
