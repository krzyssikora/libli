"""Forms for creating and editing the per-type lesson and question content elements."""

import re

from django import forms
from django.forms import inlineformset_factory
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _

from courses import fillblank
from courses import guessnumber
from courses import switchgate
from courses import switchgrid
from courses.embed import extract_embed_url
from courses.embed import parse_iframe_dimensions
from courses.marking import parse_number
from courses.models import CalloutElement
from courses.models import Choice
from courses.models import ChoiceGridQuestionElement
from courses.models import ChoiceQuestionElement
from courses.models import DragFillBlankQuestionElement
from courses.models import DragToImageQuestionElement
from courses.models import DragZone
from courses.models import ExtendedResponseQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import FillGateElement
from courses.models import FillTableElement
from courses.models import GalleryElement
from courses.models import GridColumn
from courses.models import GridRow
from courses.models import GuessNumberElement
from courses.models import HtmlElement
from courses.models import IframeElement
from courses.models import ImageElement
from courses.models import MarkDoneElement
from courses.models import MarkDoneItem
from courses.models import MatchPair
from courses.models import MatchPairQuestionElement
from courses.models import MathElement
from courses.models import MediaAsset
from courses.models import MultiGridColumn
from courses.models import MultiGridQuestionElement
from courses.models import MultiGridRow
from courses.models import QuestionElement
from courses.models import RevealGateElement
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from courses.models import SlideBreakElement
from courses.models import SpoilerElement
from courses.models import StepperElement
from courses.models import StepperStep
from courses.models import SwitchGateElement
from courses.models import SwitchGridElement
from courses.models import TableElement
from courses.models import TabsElement
from courses.models import TextElement
from courses.models import TwoColumnElement
from courses.models import VideoElement
from courses.sanitize import sanitize_cell
from courses.sanitize import sanitize_html
from courses.transfer.schema import TransferError
from courses.transfer.schema import check_decimal_str
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


class SlideBreakElementForm(forms.ModelForm):
    class Meta:
        model = SlideBreakElement
        fields = []  # field-less: a break has nothing to edit


class RevealGateElementForm(forms.ModelForm):
    class Meta:
        model = RevealGateElement
        fields = ["label"]


class SpoilerElementForm(forms.ModelForm):
    class Meta:
        model = SpoilerElement
        fields = ["label", "body"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # A nested spoiler edits its children via the nested editor rows, not this
        # flat form; drop `body` so a save can never blank it or orphan children.
        inst = self.instance
        if inst is not None and inst.pk and inst.resolved_children():
            self.fields.pop("body", None)


class CalloutElementForm(forms.ModelForm):
    class Meta:
        model = CalloutElement
        fields = ["kind", "heading", "body"]


class FillGateElementForm(forms.ModelForm):
    parsed_blanks = None  # list[list[str]] after a successful clean_stem

    class Meta:
        model = FillGateElement
        fields = ["stem"]
        widgets = {"stem": forms.Textarea(attrs={"rows": 3, "data-rte-source": ""})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Editing: show the author's {{answer}} markup, not the stored ￿n￿ token-stem.
        if self.instance and self.instance.pk:
            self.initial["stem"] = fillblank.to_author_stem(
                self.instance.stem, self.instance.answers or []
            )

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

    def save(self, commit=True):
        # `answers` is not a form field, so set it from the parsed blanks here.
        self.instance.answers = self.parsed_blanks or []
        return super().save(commit=commit)


# gettext_LAZY is mandatory: an eager gettext() here froze labels to English
# once already (PR #46). Keyed by GuessNumberError.code.
_GUESS_STEM_ERRORS = {
    "token_count": _("Write the answer in double braces, e.g. {{42}}."),
    "alternatives": _(
        'Use exactly one answer in braces — alternatives separated by "|" are '
        "not supported here."
    ),
}


class GuessNumberElementForm(forms.ModelForm):
    parsed_target = None  # Decimal after a successful clean_stem

    class Meta:
        model = GuessNumberElement
        fields = ["stem", "tolerance", "success_message"]  # target is DERIVED

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Same ','/'.' leniency the students get (PL/EN bilingual), and it makes
        # tolerance optional — a DecimalField(default=0) formfield is required.
        self.fields["tolerance"] = forms.CharField(required=False)
        if self.instance and self.instance.pk:
            # Show the author their token, not the raw <SENTINEL>0<SENTINEL> stem —
            # without this to_author_stem has no caller at all.
            self.initial["stem"] = guessnumber.to_author_stem(
                self.instance.stem, self.instance.target
            )
            # ...and canonical tolerance text, or a CharField str()s the DB
            # Decimal and shows "0.00000000".
            self.initial["tolerance"] = guessnumber.format_target(
                self.instance.tolerance
            )

    def clean_stem(self):
        raw = self.cleaned_data.get("stem", "")
        clean = fillblank.strip_sentinel(sanitize_html(raw))
        try:
            token_stem, raw_target = guessnumber.parse_stem(clean)
        except guessnumber.GuessNumberError as e:
            raise forms.ValidationError(_GUESS_STEM_ERRORS[e.code]) from e
        parsed = parse_number(raw_target)
        if parsed is None:
            raise forms.ValidationError(
                _("The answer must be a number (e.g. 42 or 3,14).")
            )
        try:
            # target is not a form field, so _post_clean excludes it from
            # full_clean and its DecimalValidator never fires. Without this the
            # DB raises a numeric-overflow DataError (a 500).
            check_decimal_str(str(parsed), "target", 20, 8)
        except TransferError as e:
            raise forms.ValidationError(
                _(
                    "The answer has too many digits (at most 12 before and 8 "
                    "after the decimal point)."
                )
            ) from e
        self.parsed_target = parsed
        return token_stem

    def clean_tolerance(self):
        raw = self.cleaned_data.get("tolerance", "")
        if not raw:
            return 0
        parsed = parse_number(raw)
        if parsed is None:
            raise forms.ValidationError(_("Enter a number (e.g. 3.14 or 3,14)."))
        if parsed < 0:
            raise forms.ValidationError(_("Tolerance cannot be negative."))
        return parsed

    def _post_clean(self):
        # NOT in save(): ModelForm.save() reads self.errors, and THAT is what
        # triggers full_clean() -> clean_stem() -> parsed_target. A save()
        # override assigning self.instance.target first would read None, and
        # construct_instance won't repair it (target isn't in Meta.fields), so
        # the row inserts NULL -> IntegrityError. _post_clean runs after
        # _clean_fields by construction, so parsed_target is always set here.
        super()._post_clean()
        if self.parsed_target is not None:
            self.instance.target = self.parsed_target


_MIN_OPTIONS = 2
_MIN_ROWS = 6


class SwitchGateElementForm(forms.Form):
    """Plain (non-Model) form for the Choose & confirm gate. Options are a
    variable-length list posted under the repeated field name ``option``; the
    correct one is the ``answer`` radio's 0-based row index."""

    stem = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "data-rte-source": ""}),
    )

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance if instance is not None else SwitchGateElement()
        self._token_stem = ""
        self._options = []
        self._answer = 0
        super().__init__(*args, **kwargs)
        if instance is not None and instance.pk:
            self.initial["stem"] = switchgate.to_author_stem(instance.stem)

    def _posted_options(self):
        data = self.data
        return data.getlist("option") if hasattr(data, "getlist") else []

    def option_rows(self):
        """Rows for the editor partial. On a BOUND (POST) form — e.g. a failed
        validation re-render — prefer the posted options + answer so the author's
        input isn't lost; otherwise use the instance (edit) or blanks (create).
        Padded to at least _MIN_ROWS."""
        if self.is_bound:
            opts = list(self._posted_options())
            try:
                answer = int(self.data.get("answer"))
            except (TypeError, ValueError):
                answer = -1
        else:
            opts = list(self.instance.options or [])
            answer = self.instance.answer if self.instance.pk else -1
        n = max(_MIN_ROWS, len(opts) + 1)
        rows = []
        for i in range(n):
            rows.append(
                {"value": opts[i] if i < len(opts) else "", "checked": i == answer}
            )
        return rows

    def clean(self):
        cleaned = super().clean()
        # --- stem: sanitise, strip stray sentinels, require exactly one {{choice}}
        raw_stem = cleaned.get("stem", "") or ""
        clean_stem = fillblank.strip_sentinel(sanitize_html(raw_stem))
        try:
            self._token_stem = switchgate.parse_stem(clean_stem)
        except switchgate.SwitchGateError:
            self.add_error(
                "stem", _("Mark the choice position with {{choice}} exactly once.")
            )
        # --- options: sanitise, drop trailing blanks, reject interior blanks / <2
        raw = [sanitize_cell(o or "") for o in self._posted_options()]
        while raw and raw[-1] == "":
            raw.pop()
        if any(o == "" for o in raw):
            self.add_error(None, _("Options cannot be empty."))
        elif len(raw) < _MIN_OPTIONS:
            self.add_error(None, _("Add at least two options."))
        self._options = raw
        # --- answer: integer, in range
        raw_answer = self.data.get("answer") if hasattr(self.data, "get") else None
        try:
            self._answer = int(raw_answer)
        except (TypeError, ValueError):
            self.add_error(None, _("Select the correct option."))
            self._answer = -1
        if self._options and not (0 <= self._answer < len(self._options)):
            self.add_error(None, _("Select the correct option."))
        return cleaned

    def save(self, commit=True):
        self.instance.stem = self._token_stem
        self.instance.options = self._options
        self.instance.answer = self._answer
        if commit:
            self.instance.save()
        return self.instance


_SG_SEED_STEM = "2 {{choice}} 2 = 4"  # create seed (math literal, not translated)


class SwitchGridElementForm(forms.Form):
    """Plain (non-Model) form for the Switch grid self-check. The grid is posted as
    indexed fields: line-{i}-stem, line-{i}-c{j}-opt (repeated), line-{i}-c{j}-ans.
    Indices are append-only; gaps and blanks are compacted at clean() time."""

    prompt = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    _LINE_STEM_RE = re.compile(r"^line-(\d+)-stem$")
    _CYC_RE = re.compile(r"^line-(\d+)-c(\d+)-(opt|ans)$")

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance if instance is not None else SwitchGridElement()
        self._lines = []  # normalized, ready to store
        super().__init__(*args, **kwargs)
        if instance is not None and instance.pk:
            self.initial["prompt"] = instance.prompt

    # ---- POST discovery helpers -------------------------------------------------
    def _line_indices(self):
        """Sorted line indices present in the POST (any line-{i}-* key)."""
        idx = set()
        for key in self.data.keys():
            m = self._LINE_STEM_RE.match(key)
            if m:
                idx.add(int(m.group(1)))
            m = self._CYC_RE.match(key)
            if m:
                idx.add(int(m.group(1)))
        return sorted(idx)

    def _cycler_indices(self, i):
        """Sorted cycler indices present for line i."""
        idx = set()
        for key in self.data.keys():
            m = self._CYC_RE.match(key)
            if m and int(m.group(1)) == i:
                idx.add(int(m.group(2)))
        return sorted(idx)

    def _opts_for(self, i, j):
        name = f"line-{i}-c{j}-opt"
        data = self.data
        return data.getlist(name) if hasattr(data, "getlist") else []

    # ---- validation -------------------------------------------------------------
    def clean(self):
        cleaned = super().clean()
        cleaned["prompt"] = (cleaned.get("prompt") or "").strip()
        lines = []
        total_cyclers = 0
        # Collect the two per-cycler problems as flags and surface each message ONCE
        # after the loops -- otherwise N under-filled cyclers each add the same
        # non-field error (and a missing answer added it twice), so 2 cyclers showed
        # "Select the correct option in every cycler" four times.
        needs_answer = False
        needs_two_options = False
        for i in self._line_indices():
            raw_stem = self.data.get(f"line-{i}-stem", "") or ""
            clean_stem = fillblank.strip_sentinel(sanitize_html(raw_stem))
            token_stem, marker_count = switchgrid.parse_stem_multi(clean_stem)

            cyclers = []
            for j in self._cycler_indices(i):
                raw_opts = [sanitize_cell(o or "") for o in self._opts_for(i, j)]
                # remember which posted slots survive, to remap the answer
                kept = [(k, o) for k, o in enumerate(raw_opts) if o != ""]
                if not kept:
                    continue  # wholly-blank cycler slot -> not present
                try:
                    ans_posted = int(self.data.get(f"line-{i}-c{j}-ans"))
                except (TypeError, ValueError):
                    ans_posted = -1  # missing/invalid -> range check flags it
                # remap posted answer onto the compacted (non-blank) list
                remap = {orig_k: new_k for new_k, (orig_k, _o) in enumerate(kept)}
                options = [o for _k, o in kept]
                answer = remap.get(ans_posted, -1)
                if len(options) < _MIN_OPTIONS:
                    needs_two_options = True
                if not (0 <= answer < len(options)):
                    needs_answer = True
                cyclers.append({"options": options, "answer": answer})

            # drop wholly-blank line (empty stem AND no surviving cyclers)
            if not clean_stem.strip() and not cyclers:
                continue
            if marker_count != len(cyclers):
                self.add_error(
                    None,
                    _("Line %(n)d: mark each cycler with {{choice}} exactly once.")
                    % {"n": len(lines) + 1},
                )
            lines.append({"stem": token_stem, "cyclers": cyclers})
            total_cyclers += len(cyclers)

        if needs_two_options:
            self.add_error(None, _("Each cycler needs at least two options."))
        if needs_answer:
            self.add_error(None, _("Select the correct option in every cycler."))
        if not lines:
            self.add_error(None, _("Add at least one line."))
        if total_cyclers < 1:
            self.add_error(None, _("Add at least one cycler with options."))
        self._lines = lines
        return cleaned

    def save(self, commit=True):
        self.instance.prompt = self.cleaned_data.get("prompt", "")
        self.instance.lines = self._lines
        if commit:
            self.instance.save()
        return self.instance

    # ---- edit re-populate (feeds _edit_switchgrid.html) -------------------------
    def _posted_lines(self):
        """Author-form lines reconstructed from a BOUND POST, so a validation-error
        re-render preserves exactly what the author typed (raw stems/options, blanks
        included). Mirrors SwitchGateElementForm.option_rows()'s is_bound branch."""
        out = []
        for i in self._line_indices():
            cyclers = []
            for j in self._cycler_indices(i):
                try:
                    answer = int(self.data.get(f"line-{i}-c{j}-ans"))
                except (TypeError, ValueError):
                    answer = -1
                cyclers.append(
                    {"options": list(self._opts_for(i, j)), "answer": answer}
                )
            out.append(
                {"stem": self.data.get(f"line-{i}-stem", "") or "", "cyclers": cyclers}
            )
        return out

    def line_rows(self):
        """Editor-partial structure (NO padding): {index, stem, cyclers:[{index,
        options:[{value, checked}]}]}. Bound form mirrors posted data (422 keeps the
        author's grid); edit mirrors instance.lines; create = one seeded line."""
        if self.is_bound:
            source = self._posted_lines()
        elif self.instance.pk:
            source = [
                {
                    "stem": switchgrid.to_author_stem_multi(line["stem"]),
                    "cyclers": line.get("cyclers", []) or [],
                }
                for line in (self.instance.lines or [])
            ]
        else:
            # create default: one seeded line, one cycler, two empty option inputs
            source = [
                {
                    "stem": _SG_SEED_STEM,
                    "cyclers": [{"options": ["", ""], "answer": -1}],
                }
            ]

        rows = []
        for i, line in enumerate(source):
            cyclers = []
            for j, cyc in enumerate(line.get("cyclers", []) or []):
                opts = (cyc or {}).get("options", []) or []
                answer = cyc.get("answer", -1) if cyc else -1
                cyclers.append(
                    {
                        "index": j,
                        "options": [
                            {"value": o, "checked": k == answer}
                            for k, o in enumerate(opts)
                        ],
                    }
                )
            rows.append({"index": i, "stem": line.get("stem", ""), "cyclers": cyclers})
        return rows


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
    fields=["text", "is_correct", "feedback"],
    widgets={
        "feedback": forms.Textarea(
            attrs={
                "rows": 2,
                "maxlength": 500,
                # No-JS baseline; editor.js swaps in a correct/distractor-aware prompt.
                "placeholder": _(
                    "Optional — shown if the student gets this option wrong"
                ),
            }
        )
    },
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


class ChoiceGridQuestionElementForm(_MarkingFieldsMixin, forms.ModelForm):
    class Meta:
        model = ChoiceGridQuestionElement
        fields = ["stem", "explanation", "marking_mode", "max_attempts", "max_marks"]
        widgets = {
            "stem": forms.Textarea(attrs={"rows": 2, "data-rte-source": ""}),
            "explanation": forms.Textarea(attrs={"rows": 2, "data-rte-source": ""}),
        }


class _GridColumnForm(forms.ModelForm):
    temp_id = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = GridColumn
        fields = ["label"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # On the EDIT path, seed a saved column's temp_id from its pk so the row
        # selects (which seed correct_temp_id from correct_column_id, i.e. the same
        # pk) reconstruct the column<->row linkage. The linkage is client-only and NOT
        # persisted, so without this an edit GET would render blank temp-ids and lose
        # every row's saved correct-column selection. New (pk-less) columns keep a
        # blank temp_id and get a fresh client id from choicegrid.js.
        if self.instance and self.instance.pk:
            self.fields["temp_id"].initial = str(self.instance.pk)

    def has_changed(self):
        # A blank added/extra row still submits a non-empty hidden temp_id (JS assigns
        # one), which would make Django's default has_changed() True and force
        # validation of the required `label` -> a spurious 422. Key has_changed ONLY on
        # the visible model field so a label-blank row is pruned, not validated.
        return "label" in self.changed_data


class BaseGridColumnFormSet(forms.BaseInlineFormSet):
    """>=1 non-deleted, non-blank column (mirrors BaseMatchPairFormSet)."""

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        kept = [
            f
            for f in self.forms
            if f.cleaned_data
            and not f.cleaned_data.get("DELETE")
            and f.cleaned_data.get("label")
        ]
        if len(kept) < 1:
            raise forms.ValidationError(_("Add at least one column."))


class _GridRowForm(forms.ModelForm):
    # required=False: a blank added/extra row (whose correct-column <select> submits
    # its default option) must not hard-fail on this hidden field. Completeness of a
    # KEPT row is enforced by BaseGridRowFormSet.clean below.
    correct_temp_id = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = GridRow
        # correct_column resolved in save_element, not bound here
        fields = ["statement"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # On the EDIT path, seed correct_temp_id from the saved correct_column_id (the
        # column's pk, which _GridColumnForm also uses as its temp_id) so the rendered
        # row select restores the saved selection and save_element re-resolves it.
        if self.instance and self.instance.pk and self.instance.correct_column_id:
            self.fields["correct_temp_id"].initial = str(
                self.instance.correct_column_id
            )

    def has_changed(self):
        # Same rationale as _GridColumnForm: prune a statement-blank row instead of
        # validating it (the <select> + hidden field would otherwise trip has_changed).
        return "statement" in self.changed_data


class BaseGridRowFormSet(forms.BaseInlineFormSet):
    """>=1 non-deleted, non-blank row; each kept row must carry a correct_temp_id."""

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        kept = [
            f
            for f in self.forms
            if f.cleaned_data
            and not f.cleaned_data.get("DELETE")
            and f.cleaned_data.get("statement")
        ]
        if len(kept) < 1:
            raise forms.ValidationError(_("Add at least one row."))
        for f in kept:
            if not f.cleaned_data.get("correct_temp_id"):
                raise forms.ValidationError(_("Each row needs a correct column."))


GridColumnFormSet = inlineformset_factory(
    ChoiceGridQuestionElement,
    GridColumn,
    form=_GridColumnForm,
    formset=BaseGridColumnFormSet,
    extra=0,
    can_delete=True,
)
GridRowFormSet = inlineformset_factory(
    ChoiceGridQuestionElement,
    GridRow,
    form=_GridRowForm,
    formset=BaseGridRowFormSet,
    extra=0,
    can_delete=True,
)


def build_choicegrid_columns_formset(
    *, data=None, files=None, instance=None, prefix="columns"
):
    return GridColumnFormSet(data=data, files=files, instance=instance, prefix=prefix)


def build_choicegrid_rows_formset(
    *, data=None, files=None, instance=None, prefix="rows"
):
    return GridRowFormSet(data=data, files=files, instance=instance, prefix=prefix)


class MultiGridQuestionElementForm(_MarkingFieldsMixin, forms.ModelForm):
    class Meta:
        model = MultiGridQuestionElement
        fields = ["stem", "explanation", "marking_mode", "max_attempts", "max_marks"]
        widgets = {
            "stem": forms.Textarea(attrs={"rows": 2, "data-rte-source": ""}),
            "explanation": forms.Textarea(attrs={"rows": 2, "data-rte-source": ""}),
        }


class _MultiGridColumnForm(forms.ModelForm):
    temp_id = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = MultiGridColumn
        fields = ["label"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Seed a saved column's temp_id from its pk on edit, so the row checkbox
        # sets (which seed correct_temp_ids from the columns' pks) reconstruct the
        # client-only column<->row linkage. New columns keep a blank temp_id.
        if self.instance and self.instance.pk:
            self.fields["temp_id"].initial = str(self.instance.pk)

    def has_changed(self):
        # Key on the visible field only so a blank added column (whose hidden
        # temp_id JS fills) is pruned, not validated into a spurious 422.
        return "label" in self.changed_data


class BaseMultiGridColumnFormSet(forms.BaseInlineFormSet):
    """>=1 non-deleted, non-blank column."""

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        kept = [
            f
            for f in self.forms
            if f.cleaned_data
            and not f.cleaned_data.get("DELETE")
            and f.cleaned_data.get("label")
        ]
        if len(kept) < 1:
            raise forms.ValidationError(_("Add at least one column."))


def _parse_temp_ids(raw):
    """Comma-joined temp-id string -> list of non-blank ids (order-preserving)."""
    return [t for t in (raw or "").split(",") if t.strip()]


class _MultiGridRowForm(forms.ModelForm):
    # Comma-joined set of correct-column temp-ids. required=False: a blank added row
    # must not hard-fail; completeness of a KEPT row is enforced in the formset clean.
    correct_temp_ids = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = MultiGridRow
        # correct_columns M2M resolved in save_element, not bound here
        fields = ["statement"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Seed correct_temp_ids from the saved M2M (column pks == their temp_ids) on
        # edit, so the rendered checkboxes restore the saved set and save_element
        # re-resolves it. Guarded on pk (unsaved rows have no M2M).
        if self.instance and self.instance.pk:
            pks = list(self.instance.correct_columns.values_list("pk", flat=True))
            if pks:
                self.fields["correct_temp_ids"].initial = ",".join(
                    str(pk) for pk in pks
                )

    def has_changed(self):
        return "statement" in self.changed_data


class BaseMultiGridRowFormSet(forms.BaseInlineFormSet):
    """>=1 non-deleted, non-blank row; each kept row's raw correct_temp_ids must
    parse to >=1 id (a within-formset check; surviving-column resolution and the
    zero-survivors error live in save_element)."""

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        kept = [
            f
            for f in self.forms
            if f.cleaned_data
            and not f.cleaned_data.get("DELETE")
            and f.cleaned_data.get("statement")
        ]
        if len(kept) < 1:
            raise forms.ValidationError(_("Add at least one row."))
        for f in kept:
            if not _parse_temp_ids(f.cleaned_data.get("correct_temp_ids")):
                raise forms.ValidationError(
                    _("Each row needs at least one correct column.")
                )


MultiGridColumnFormSet = inlineformset_factory(
    MultiGridQuestionElement,
    MultiGridColumn,
    form=_MultiGridColumnForm,
    formset=BaseMultiGridColumnFormSet,
    extra=0,
    can_delete=True,
)
MultiGridRowFormSet = inlineformset_factory(
    MultiGridQuestionElement,
    MultiGridRow,
    form=_MultiGridRowForm,
    formset=BaseMultiGridRowFormSet,
    extra=0,
    can_delete=True,
)


def build_multigrid_columns_formset(
    *, data=None, files=None, instance=None, prefix="columns"
):
    return MultiGridColumnFormSet(
        data=data, files=files, instance=instance, prefix=prefix
    )


def build_multigrid_rows_formset(
    *, data=None, files=None, instance=None, prefix="rows"
):
    return MultiGridRowFormSet(data=data, files=files, instance=instance, prefix=prefix)


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


def _scan_spans(cells):
    """Detect whether a raw, author-supplied grid is spanning, and reject an
    out-of-range span while we are here.

    Returns True iff any cell carries a real colspan/rowspan (> 1). Detection
    goes through TableElement._span so it cannot diverge from the branch
    normalize_data will actually take -- notably, _span does NOT coerce, so a
    string "3" is not a span.

    The RANGE check deliberately reads the RAW int instead: _span's return is
    already clamped to the cap and so can never look out of range. Values below
    2 are not spans at all and are ignored rather than rejected, matching both
    _span (None) and layout_dims (counts as 1).

    Coerces defensively at both levels, mirroring normalize_data: a non-list
    `cells` is empty, a non-list row is skipped, a non-dict cell is skipped.
    TableElementForm has its own guards ahead of this, but
    FillTableElementForm does not -- without this, a crafted {"cells": 5}
    would be `for r in 5` -> TypeError -> 500."""
    rows = cells if isinstance(cells, list) else []
    spanning = False
    for row in rows:
        if not isinstance(row, list):
            continue
        for cell in row:
            if not isinstance(cell, dict):
                continue
            for key, cap in (
                ("colspan", TableElement.MAX_COLS),
                ("rowspan", TableElement.MAX_ROWS),
            ):
                raw = cell.get(key)
                if isinstance(raw, bool) or not isinstance(raw, int) or raw < 2:
                    continue
                if raw > cap:
                    # Two msgids, not one interpolated with 20 or 50: a single
                    # nounless string ("more than 20.") cannot be translated
                    # correctly, and Polish needs the axis word to inflect.
                    raise forms.ValidationError(
                        _("A merged cell may not span more than %(n)d columns.")
                        % {"n": cap}
                        if key == "colspan"
                        else _("A merged cell may not span more than %(n)d rows.")
                        % {"n": cap}
                    )
            if (
                TableElement._span(cell, "colspan") is not None
                or TableElement._span(cell, "rowspan") is not None
            ):
                spanning = True
    return spanning


def _caps_ok(form, cells):
    """True iff the grid's LAYOUT dimensions are within the caps, or are no
    larger than what is already stored (grandfathering).

    The 26-column 130_kombinatoryka table already exceeds MAX_COLS, so an
    absolute cap would make an existing element permanently unsaveable. The
    caps therefore gate GROWTH, per axis, against the pre-save DB value.
    (0, 0) for an unsaved instance -- an explicit special case, because
    normalize_data({}) returns the default 2x2, not an empty grid."""
    model = form._meta.model
    # Read the caps off the FORM'S model, not TableElement: they are equal
    # today (FillTableElement aliases them), but hardcoding one model's caps
    # here while the error message interpolates the other's would silently
    # disagree the moment they diverge.
    max_cols, max_rows = model.MAX_COLS, model.MAX_ROWS
    width, height = TableElement.layout_dims(cells)
    if form.instance.pk is None:
        stored_w, stored_h = 0, 0
    else:
        stored = model.normalize_data(form.instance.data)["cells"]
        stored_w, stored_h = TableElement.layout_dims(stored)
    if width > max_cols and width > stored_w:
        return False
    if height > max_rows and height > stored_h:
        return False
    return True


class TableElementForm(forms.ModelForm):
    class Meta:
        model = TableElement
        fields = ["data"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # JSONField(default=dict) yields a required=True form field, and Django's
        # EMPTY_VALUES includes {} — so an empty payload (and the "add a table,
        # Save without editing" flow, whose hidden field is "" because the JS does
        # not serialize on init) would fail "This field is required" BEFORE
        # clean_data runs. Make it optional; clean_data supplies the default grid.
        self.fields["data"].required = False

    def clean_data(self):
        data = self.cleaned_data.get("data")
        # Empty / missing / no-cells -> the default 2x2 (NOT an error). This is
        # the plain add+save path and the empty-{} case.
        if not isinstance(data, dict) or not data.get("cells"):
            return TableElement.normalize_data({})
        rows = data["cells"]
        # `cells` present but not a list (e.g. a number/string from a crafted
        # POST) is malformed — reject cleanly rather than crashing on iteration.
        if not isinstance(rows, list):
            raise forms.ValidationError(_("A table needs at least one cell."))
        widths = {len(r) if isinstance(r, list) else -1 for r in rows}
        # Present-but-malformed grid IS an error (non-list row, or EVERY row
        # empty). Note this is not a per-row zero-width rejection: a single
        # empty row is legal, and is exactly what a full-width multi-row merge
        # produces.
        if -1 in widths or widths == {0}:
            raise forms.ValidationError(_("A table needs at least one cell."))
        # Only now decide which structural check applies. A spanning grid is
        # ragged by construction, so the uniform-width rule cannot hold for it.
        spanning = _scan_spans(rows)
        if not spanning and len(widths) != 1:
            raise forms.ValidationError(
                _("All table rows must have the same number of cells.")
            )
        if not _caps_ok(self, rows):
            raise forms.ValidationError(
                _("Tables are limited to %(r)d rows by %(c)d columns.")
                % {"r": TableElement.MAX_ROWS, "c": TableElement.MAX_COLS}
            )
        # Coerce enums / fill cell defaults (does not resize a valid grid).
        return TableElement.normalize_data(data)


class FillTableElementForm(_CourseScopedMediaForm):
    """Fill-in table. `data` JSON holds {cells:[[cell,...],...]}; image cells carry
    a `media` id that is course-scoped against the referenced image in clean_data
    (mirrors GalleryElementForm — the same author-submitted-pk risk)."""

    media_kind = "image"

    class Meta:
        model = FillTableElement
        fields = ["data"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # JSONField(default=dict) is required=True and {} is an EMPTY_VALUE, so an
        # unedited add would fail "required" before clean_data. Make optional.
        self.fields["data"].required = False

    def clean_data(self):
        from courses.filltable import answer_cells
        from courses.filltable import is_blank_answer

        data = self.cleaned_data.get("data")
        raw_cells = data.get("cells") if isinstance(data, dict) else None
        # Raw scan FIRST: rejects an out-of-range span before normalize_data
        # clamps it out of sight. Coerces malformed input rather than raising.
        _scan_spans(raw_cells)
        nd = FillTableElement.normalize_data(data if isinstance(data, dict) else {})
        cells = nd["cells"]
        if not _caps_ok(self, cells):
            raise forms.ValidationError(
                _("Tables are limited to %(r)d rows by %(c)d columns.")
                % {"r": FillTableElement.MAX_ROWS, "c": FillTableElement.MAX_COLS}
            )
        answers = list(answer_cells(cells))
        if not answers:
            raise forms.ValidationError(
                _("Mark at least one answer cell (use the “Answer cell” button).")
            )
        if any(is_blank_answer(ans) for _r, _c, ans in answers):
            raise forms.ValidationError(
                _(
                    "An answer cell is blank — type its accepted answer, "
                    "or make it a normal cell."
                )
            )
        # Course-scope image cells (mirrors GalleryElementForm): every image cell's
        # media must be an image in this course.
        img_ids = {c["media"] for row in cells for c in row if c.get("kind") == "image"}
        if img_ids and self.course is not None:
            allowed = set(
                MediaAsset.objects.filter(
                    course=self.course, kind="image", pk__in=img_ids
                ).values_list("pk", flat=True)
            )
            if img_ids - allowed:
                raise forms.ValidationError(
                    _("A table image is not an image in this course.")
                )
        return nd


class GalleryElementForm(_CourseScopedMediaForm):
    """Image gallery/carousel. `data` JSON holds {desc_pos, images:[{media,desc}]};
    course-scoping is enforced against the referenced image ids in clean_data."""

    media_kind = "image"

    class Meta:
        model = GalleryElement
        fields = ["data"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Same rationale as TableElementForm: JSONField(default=dict) is required
        # and {} is empty, so an unedited add would fail before clean_data.
        self.fields["data"].required = False

    def clean_data(self):
        data = GalleryElement.normalize_data(self.cleaned_data.get("data"))
        # normalize_data already dropped entries without a valid int media, so a
        # count shortfall here also catches "some ids were malformed".
        raw = self.cleaned_data.get("data")
        if isinstance(raw, dict) and not isinstance(raw.get("images"), list):
            raise forms.ValidationError(_("A gallery needs a list of images."))
        images = data["images"]
        if len(images) < GalleryElement.MIN_IMAGES:
            raise forms.ValidationError(
                _("A gallery needs at least %(n)d images.")
                % {"n": GalleryElement.MIN_IMAGES}
            )
        if len(images) > GalleryElement.MAX_IMAGES:
            raise forms.ValidationError(
                _("A gallery is limited to %(n)d images.")
                % {"n": GalleryElement.MAX_IMAGES}
            )
        ids = {img["media"] for img in images}
        allowed = set(
            MediaAsset.objects.filter(
                course=self.course, kind="image", pk__in=ids
            ).values_list("pk", flat=True)
        )
        if ids - allowed:
            raise forms.ValidationError(
                _("A gallery image is not an image in this course.")
            )
        return data

    @property
    def editor_rows(self):
        """Resolved [{id, thumb_url, desc}] for the editor: from submitted data
        when bound (so an invalid re-render keeps the author's picks), else from
        the instance. Unresolved ids are dropped."""
        if self.is_bound:
            source = GalleryElement.normalize_data(self._raw_data_json())
        else:
            source = GalleryElement.normalize_data(getattr(self.instance, "data", {}))
        ids = [img["media"] for img in source["images"]]
        assets = MediaAsset.objects.in_bulk(ids)
        rows = []
        for img in source["images"]:
            asset = assets.get(img["media"])
            if asset is not None:
                rows.append(
                    {"id": asset.pk, "thumb_url": asset.file.url, "desc": img["desc"]}
                )
        return rows

    def _raw_data_json(self):
        import json

        try:
            return json.loads(self.data.get("data") or "{}")
        except (ValueError, TypeError):
            return {}


class TabsElementForm(forms.ModelForm):
    """Tab labels only -- the children are Element rows, not form data. The hidden
    name="data" field is the sole authoritative input; tabs_editor.js mirrors the
    label rows into it, carrying each SURVIVING tab's id so it round-trips. Only a
    genuinely new row arrives id-less; the server mints its id here."""

    class Meta:
        model = TabsElement
        fields = ["data"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Same rationale as TableElementForm/GalleryElementForm: JSONField(default=dict)
        # is required and {} is empty, so "add tabs, Save without editing" would fail
        # "This field is required" before clean_data runs.
        self.fields["data"].required = False

    def clean_data(self):
        raw = self.cleaned_data.get("data")
        raw = raw if isinstance(raw, dict) else {}
        tabs = raw.get("tabs")
        if tabs is None:
            # Plain add + save with no edit -> the two default tabs. Built explicitly
            # rather than via normalize_data, because normalize_data is the DESTRUCTIVE
            # read-side normalizer and must never be reachable from a write path.
            return TabsElement.default_data()
        if not isinstance(tabs, list):
            raise forms.ValidationError(_("A tabs element needs a list of tabs."))
        if len(tabs) < TabsElement.MIN_TABS:
            raise forms.ValidationError(
                _("A tabs element must keep at least %(n)d tabs.")
                % {"n": TabsElement.MIN_TABS}
            )
        if len(tabs) > TabsElement.MAX_TABS:
            raise forms.ValidationError(
                _("A tabs element is limited to %(n)d tabs.")
                % {"n": TabsElement.MAX_TABS}
            )
        # Mints ids for new rows and preserves existing unique ones. Doing it HERE is
        # what lets save_element diff old-vs-new ids without ever touching a raw row.
        return TabsElement.normalize_labels_and_ids({"tabs": tabs})

    @cached_property
    def editor_rows(self):
        """[{id, label}] for the editor: from submitted data when bound (so an invalid
        re-render keeps the author's edits), else from the instance. A brand-new
        element has no stored tabs, so fall back to the same defaults clean_data
        supplies -- the editor must never render a tabs element with zero tabs.

        Cached per form instance because the fallback mints RANDOM ids: a template that
        reads this twice (once for the rows, once for a JS init blob) would otherwise
        render two different id sets in one response, desyncing them.
        """
        if self.is_bound:
            source = self._raw_data_json()
        else:
            source = getattr(self.instance, "data", {})
        rows = TabsElement.normalize_labels_and_ids(source)["tabs"]
        return rows or TabsElement.default_data()["tabs"]

    def _raw_data_json(self):
        import json

        try:
            return json.loads(self.data.get("data") or "{}")
        except (ValueError, TypeError):
            return {}


class TwoColumnElementForm(forms.ModelForm):
    """Two-column layout: the ONLY input is the column count. Columns + ids are owned
    by save_element, NOT the form. No `data` field and no clean_data -> form.save()
    never writes `columns` (so it can never clobber persisted ids on edit)."""

    column_count = forms.TypedChoiceField(
        coerce=int,
        choices=[
            (n, str(n))
            for n in range(
                TwoColumnElement.MIN_COLUMNS, TwoColumnElement.MAX_COLUMNS + 1
            )
        ],
        label=_("Number of columns"),
    )

    class Meta:
        model = TwoColumnElement
        fields = []  # bind no model fields

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            existing = getattr(self.instance, "data", None) or {}
            cols = existing.get("columns")
            n = (
                len(cols)
                if isinstance(cols, list) and cols
                else len(TwoColumnElement.default_data()["columns"])
            )
            n = max(TwoColumnElement.MIN_COLUMNS, min(TwoColumnElement.MAX_COLUMNS, n))
            self.fields["column_count"].initial = n


class StepperElementForm(forms.ModelForm):
    class Meta:
        model = StepperElement
        fields = ["prompt"]
        widgets = {
            "prompt": forms.TextInput(attrs={"maxlength": StepperElement.MAX_LEN}),
        }


class StepperStepForm(forms.ModelForm):
    class Meta:
        model = StepperStep
        fields = ["content"]


class BaseStepperFormSet(forms.BaseInlineFormSet):
    """>=MIN_STEPS and <=MAX_STEPS non-deleted, non-blank steps. Blank extra rows
    (empty content) are naturally skipped by Django, then dropped here before the
    count check — mirrors BaseMatchPairFormSet."""

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        kept = [
            f
            for f in self.forms
            if f.cleaned_data
            and not f.cleaned_data.get("DELETE")
            and (f.cleaned_data.get("content") or "").strip()
        ]
        if len(kept) < StepperElement.MIN_STEPS:
            raise forms.ValidationError(_("Add at least one step."))
        if len(kept) > StepperElement.MAX_STEPS:
            raise forms.ValidationError(
                _("A stepper can have at most %(n)d steps.")
                % {"n": StepperElement.MAX_STEPS}
            )


StepperStepFormSet = inlineformset_factory(
    StepperElement,
    StepperStep,
    form=StepperStepForm,
    formset=BaseStepperFormSet,
    fields=["content"],
    extra=1,
    can_delete=True,
)


def build_stepper_formset(*, data=None, files=None, instance=None, prefix="steps"):
    """Construct the StepperStep inline formset. Shared by render + save paths so
    validation cannot drift (mirror of build_matchpair_formset)."""
    return StepperStepFormSet(data=data, files=files, instance=instance, prefix=prefix)


class MarkDoneElementForm(forms.ModelForm):
    class Meta:
        model = MarkDoneElement
        fields = ["prompt"]
        widgets = {
            "prompt": forms.TextInput(attrs={"maxlength": MarkDoneElement.MAX_LEN})
        }


class MarkDoneItemForm(forms.ModelForm):
    class Meta:
        model = MarkDoneItem
        fields = ["content"]


class BaseMarkDoneFormSet(forms.BaseInlineFormSet):
    """>=MIN_ITEMS and <=MAX_ITEMS non-deleted, non-blank items (mirrors
    BaseStepperFormSet)."""

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        kept = 0
        for f in self.forms:
            cd = f.cleaned_data
            if not cd or cd.get("DELETE"):
                continue
            if (cd.get("content") or "").strip():
                kept += 1
        if not (MarkDoneElement.MIN_ITEMS <= kept <= MarkDoneElement.MAX_ITEMS):
            raise forms.ValidationError(
                _("A checklist needs between %(lo)s and %(hi)s items."),
                params={
                    "lo": MarkDoneElement.MIN_ITEMS,
                    "hi": MarkDoneElement.MAX_ITEMS,
                },
            )


MarkDoneItemFormSet = inlineformset_factory(
    MarkDoneElement,
    MarkDoneItem,
    form=MarkDoneItemForm,
    formset=BaseMarkDoneFormSet,
    fields=["content"],
    extra=1,
    can_delete=True,
)


def build_markdone_formset(*, data=None, files=None, instance=None, prefix="items"):
    """Construct the MarkDoneItem inline formset. Shared by render + save paths so
    validation cannot drift (mirror of build_stepper_formset)."""
    return MarkDoneItemFormSet(data=data, files=files, instance=instance, prefix=prefix)


FORM_FOR_TYPE = {
    "text": TextElementForm,
    "image": ImageElementForm,
    "video": VideoElementForm,
    "iframe": IframeElementForm,
    "math": MathElementForm,
    "html": HtmlElementForm,
    "slidebreak": SlideBreakElementForm,
    "revealgate": RevealGateElementForm,
    "spoiler": SpoilerElementForm,
    "callout": CalloutElementForm,
    "choicequestion": ChoiceQuestionElementForm,
    "shorttextquestion": ShortTextQuestionElementForm,
    "shortnumericquestion": ShortNumericQuestionElementForm,
    "fillblankquestion": FillBlankQuestionElementForm,
    "dragfillblankquestion": DragFillBlankQuestionElementForm,
    "matchpairquestion": MatchPairQuestionElementForm,
    "choicegridquestion": ChoiceGridQuestionElementForm,
    "multigridquestion": MultiGridQuestionElementForm,
    "dragtoimagequestion": DragToImageQuestionElementForm,
    "extendedresponsequestion": ExtendedResponseQuestionElementForm,
    "table": TableElementForm,
    "filltable": FillTableElementForm,
    "gallery": GalleryElementForm,
    "tabs": TabsElementForm,
    "twocolumn": TwoColumnElementForm,
    "fillgate": FillGateElementForm,
    "switchgate": SwitchGateElementForm,
    "switchgrid": SwitchGridElementForm,
    "stepper": StepperElementForm,
    "markdone": MarkDoneElementForm,
    "guessnumber": GuessNumberElementForm,
}
