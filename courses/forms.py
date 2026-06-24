from django import forms
from django.db.models import Q
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from courses.models import Course


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
