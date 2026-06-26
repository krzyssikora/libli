from decimal import Decimal

from django import forms
from django.core.validators import MaxValueValidator
from django.db.models import Q
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from courses.models import ContentNode
from courses.models import Course
from courses.ordering import PRESET_FLAGS
from courses.ordering import kinds_for_preset
from courses.ordering import preset_for_flags


def unique_course_slug(title, exclude_pk=None):
    """slugify(title); on collision append the smallest free -2, -3, … suffix."""
    base = slugify(title) or "course"
    qs = Course.objects.all()
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    if not qs.filter(slug=base).exists():
        return base
    n = 2
    while qs.filter(slug=f"{base}-{n}").exists():
        n += 1
    return f"{base}-{n}"


class CourseForm(forms.ModelForm):
    # Non-model picker: writes uses_parts/uses_chapters/uses_sections in save().
    # required-ness + initial are set per create/edit in __init__.
    structure = forms.ChoiceField(
        required=False,
        widget=forms.RadioSelect,
        label=_("Structure"),
        help_text=_("Which content levels this course uses."),
    )

    class Meta:
        model = Course
        fields = [
            "title",
            "slug",
            "subject",
            "language",
            "overview",
            "visibility",
            "self_enroll_cohorts",
            "owner",
            "html_css",
            "html_js",
        ]
        # Translatable labels: the model fields carry no verbose_name, so Django's
        # auto-derived labels rendered untranslated under non-English locales. Set
        # on the form, not the model, to avoid a label-only migration (per the 3b
        # visibility-choices precedent).
        labels = {
            "title": _("Title"),
            "slug": _("Slug"),
            "subject": _("Subject"),
            "language": _("Language"),
            "overview": _("Overview"),
            "visibility": _("Visibility"),
            "self_enroll_cohorts": _("Self enroll cohorts"),
            "owner": _("Owner"),
            "html_css": _("Html css"),
            "html_js": _("Html js"),
        }
        widgets = {
            "self_enroll_cohorts": forms.CheckboxSelectMultiple,
            "html_css": forms.Textarea(
                attrs={"class": "code", "rows": 10, "spellcheck": "false"}
            ),
            "html_js": forms.Textarea(
                attrs={"class": "code", "rows": 10, "spellcheck": "false"}
            ),
        }
        # NOTE: Django renders form help_text UNescaped — keep literal HTML tags
        # (e.g. <style>, <script>) out of these strings or they inject into the page.
        help_texts = {
            "slug": _("Optional — generated from the title if left blank."),
            "visibility": _(
                "Open courses appear in the student catalog for self-enrolment "
                "(optionally limited to the chosen cohorts below). Assigned courses "
                "are enrolled only by a teacher/admin or via a group."
            ),
            "self_enroll_cohorts": _("Leave empty = open to all students."),
            "html_css": _(
                "Injected as a style block into every HTML element's sandbox "
                "in this course. Plain CSS only."
            ),
            "html_js": _(
                "Runs inside every HTML element's isolated sandbox (shared by all "
                "elements in the course). Constraints: no external script tags or "
                "CDNs — paste libraries inline here; no localStorage or cookies (put "
                "per-unit data in the unit's seed, e.g. window.SEED); no eval() or "
                "new Function(); no network (fetch/XHR). Inline and display LaTeX "
                "math render automatically — do not add MathJax."
            ),
        }

    def __init__(self, *args, can_assign_owner=True, **kwargs):
        super().__init__(*args, **kwargs)
        # slug optional on the form: auto-suggested from title if left blank.
        self.fields["slug"].required = False
        # Only PAs (courses.change_course) may (re)assign owner; drop the field for a
        # plain owner editing their own course, so they can't reassign ownership.
        if not can_assign_owner:
            self.fields.pop("owner")

        # Clarify the bare model choices ("Assigned"/"Open") with self-enrolment
        # wording. Done on the form (not the model) to avoid a label-only migration.
        self.fields["visibility"].choices = [
            ("assigned", _("Assigned — enrolment by a teacher/admin or group only")),
            ("open", _("Open — students can self-enroll via the catalog")),
        ]

        from grouping.models import Cohort

        selected_pks = (
            list(self.instance.self_enroll_cohorts.values_list("pk", flat=True))
            if self.instance.pk
            else []
        )
        # Non-archived cohorts, plus any already-selected (possibly-archived) cohort,
        # as a single filterable Q-OR (NOT .union(), which can't be ordered for the
        # checkbox widget). Keeps an archived-after-selection cohort from being dropped.
        self.fields["self_enroll_cohorts"].queryset = Cohort.objects.filter(
            Q(archived=False) | Q(pk__in=selected_pks)
        ).order_by("-is_default", "name")
        self.fields["self_enroll_cohorts"].required = False

        def _chain(kinds):
            labels = [str(_("Course"))] + [
                str(ContentNode.Kind(k).label) for k in kinds
            ]
            return " › ".join(labels)

        preset_labels = {
            "flat": _("Flat"),
            "chapters": _("Chapters"),
            "parts": _("Parts"),
            "full": _("Full"),
        }
        self.fields["structure"].choices = [
            (key, f"{preset_labels[key]} — {_chain(kinds_for_preset(key))}")
            for key in PRESET_FLAGS
        ]

        if self.instance.pk is None:  # creating
            self.fields["structure"].required = True
            self.fields["structure"].initial = "chapters"
        else:  # editing
            current = preset_for_flags(
                self.instance.uses_parts,
                self.instance.uses_chapters,
                self.instance.uses_sections,
            )
            self.fields["structure"].required = False
            self.fields["structure"].initial = current  # None => no radio checked
            if current is None:  # Custom course
                self.fields["structure"].help_text = _(
                    "Custom: %(chain)s (keeps current structure)."
                ) % {"chain": _chain(self.instance.allowed_kinds)}

    def clean_slug(self):
        slug = self.cleaned_data.get("slug")
        if not slug:
            slug = unique_course_slug(
                self.cleaned_data.get("title", ""), exclude_pk=self.instance.pk
            )
        # explicit duplicate check → friendly field error, never a DB IntegrityError
        qs = Course.objects.filter(slug=slug)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("That slug is already in use.")
        return slug

    def clean(self):
        cleaned = super().clean()
        preset = cleaned.get("structure")
        if not preset:
            return cleaned  # no preset chosen -> flags unchanged
        parts, chapters, sections = PRESET_FLAGS[preset]
        if self.instance.pk:  # block True->False transitions for in-use levels
            transitions = [
                ("part", self.instance.uses_parts, parts),
                ("chapter", self.instance.uses_chapters, chapters),
                ("section", self.instance.uses_sections, sections),
            ]
            msgs = []
            for kind, current, target in transitions:
                if current and not target:
                    n = ContentNode.objects.filter(
                        course=self.instance, kind=kind
                    ).count()
                    if n:
                        msgs.append(
                            ngettext(
                                "%(count)d item at the %(level)s level",
                                "%(count)d items at the %(level)s level",
                                n,
                            )
                            % {"count": n, "level": ContentNode.Kind(kind).label}
                        )
            if msgs:
                raise forms.ValidationError(
                    _("Remove these before changing the structure: %(list)s.")
                    % {"list": "; ".join(msgs)}
                )
        return cleaned

    def save(self, commit=True):
        preset = self.cleaned_data.get("structure")
        if preset:
            (
                self.instance.uses_parts,
                self.instance.uses_chapters,
                self.instance.uses_sections,
            ) = PRESET_FLAGS[preset]
        return super().save(commit=commit)


class ReviewResponseForm(forms.Form):
    """Grade one [R] response: marks 0..max_marks + an optional comment."""

    earned_marks = forms.DecimalField(
        label=_("Marks awarded"),
        min_value=Decimal("0"),
        decimal_places=2,
        max_digits=7,
    )
    feedback = forms.CharField(
        label=_("Feedback (optional)"),
        widget=forms.Textarea(attrs={"rows": 4}),
        required=False,
    )

    def __init__(self, *args, max_marks, **kwargs):
        super().__init__(*args, **kwargs)
        # Setting max_value alone does NOT add a validator post-construction (the
        # DecimalField builds its MaxValueValidator from the kwarg at __init__ time);
        # the explicit append below is what enforces the bound on clean. max_value is
        # still set so the NumberInput widget renders the max="" HTML attribute.
        self.fields["earned_marks"].max_value = max_marks
        self.fields["earned_marks"].validators.append(MaxValueValidator(max_marks))
