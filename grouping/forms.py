from django import forms
from django.utils.translation import gettext_lazy as _

from grouping.models import Cohort
from grouping.models import Collection
from grouping.models import Group


class CohortForm(forms.ModelForm):
    class Meta:
        model = Cohort
        fields = ["name"]
        labels = {"name": _("Name")}

    # `is_default` and `archived` are intentionally NOT form fields: promotion
    # goes through grouping.services.promote_default, and archiving through
    # grouping.services.archive_cohort (which reassigns members to Default and
    # refuses to archive the Default cohort). Letting a plain form write either
    # would bypass those guards. They are the sole write paths.


class GroupForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ["name", "course", "teachers"]
        widgets = {"teachers": forms.CheckboxSelectMultiple}
        labels = {"name": _("Name"), "course": _("Course"), "teachers": _("Teachers")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk is not None:
            # Course is immutable after creation; lock the widget.
            self.fields["course"].disabled = True


class CollectionForm(forms.ModelForm):
    class Meta:
        model = Collection
        fields = ["name", "course", "groups"]
        widgets = {"groups": forms.CheckboxSelectMultiple}
        labels = {"name": _("Name"), "course": _("Course"), "groups": _("Groups")}

    def __init__(self, *args, owner=None, **kwargs):
        self._owner = owner
        super().__init__(*args, **kwargs)
        # Course is immutable once groups are attached.
        if self.instance.pk is not None and self.instance.groups.exists():
            self.fields["course"].disabled = True

    def clean(self):
        cleaned = super().clean()
        course = cleaned.get("course")
        groups = cleaned.get("groups")
        if course and groups:
            mismatched = [g for g in groups if g.course_id != course.pk]
            if mismatched:
                self.add_error(
                    "groups",
                    _("Every group must belong to the collection's course."),
                )
        return cleaned

    def save(self, commit=True):
        collection = super().save(commit=False)
        if self._owner is not None and collection.owner_id is None:
            collection.owner = self._owner
        if commit:
            collection.save()
            self.save_m2m()
        return collection
