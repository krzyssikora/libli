from django import forms
from django.utils.text import slugify

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
            "owner",
            "html_css",
            "html_js",
        ]
        widgets = {
            "html_css": forms.Textarea(
                attrs={"class": "code", "rows": 10, "spellcheck": "false"}
            ),
            "html_js": forms.Textarea(
                attrs={"class": "code", "rows": 10, "spellcheck": "false"}
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
