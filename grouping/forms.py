from django import forms
from django.db.models import Q
from django.utils.text import format_lazy
from django.utils.translation import gettext_lazy as _

from courses.access import manageable_courses
from courses.models import Course
from grouping.models import Allocation
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
        fields = ["name", "course", "teachers", "external_id"]
        widgets = {"teachers": forms.CheckboxSelectMultiple}
        labels = {
            "name": _("Name"),
            "course": _("Course"),
            "teachers": _("Teachers"),
            "external_id": _("Register class code"),
        }
        help_texts = {"external_id": _("Class code in your external register.")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk is not None:
            # Course is immutable after creation; lock the widget.
            self.fields["course"].disabled = True
        from grouping.services import teacher_users

        self.fields["teachers"].queryset = teacher_users()


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


class AllocationForm(forms.ModelForm):
    class Meta:
        model = Allocation
        fields = ["name", "course", "cohorts"]
        widgets = {"cohorts": forms.CheckboxSelectMultiple}
        labels = {
            "name": _("Name"),
            "course": _("Course"),
            "cohorts": _("Cohorts"),
        }
        help_texts = {
            "cohorts": _("Students in these cohorts appear as rows in the grid.")
        }

    # `archived` is intentionally not a form field: archiving goes through the
    # allocation_archive POST view, exactly as CohortForm keeps `archived` off
    # the form.

    def __init__(self, *args, user=None, **kwargs):
        self._user = user
        super().__init__(*args, **kwargs)
        # The course queryset IS the create-time permission gate (see spec):
        # a CA posting an unowned course pk fails invalid_choice, so a
        # PermissionDenied check placed after is_valid() would be unreachable.
        self.fields["course"].queryset = (
            manageable_courses(user) if user is not None else Course.objects.none()
        )
        if self.instance.pk is not None and self.instance.groups.exists():
            self.fields["course"].disabled = True
        # Keep an already-attached archived cohort selectable. Without this arm
        # its checkbox is never RENDERED, so the browser cannot post it back and
        # save_m2m() silently drops it — emptying a whole section out of the grid.
        attached = Q(pk__in=[])
        if self.instance.pk is not None:
            attached = Q(pk__in=self.instance.cohorts.values("pk"))
        self.fields["cohorts"].queryset = Cohort.objects.filter(
            Q(archived=False) | attached
        ).order_by("-is_default", "name")
        # Spec: an attached archived cohort renders with an "(archived)" suffix.
        # Cohort.__str__ is the bare name and display_name adds "(default)", so
        # without this override the archived cohort reads as an ordinary choice —
        # losing the whole point of keeping it selectable.
        self.fields["cohorts"].label_from_instance = self._cohort_label

    @staticmethod
    def _cohort_label(obj):
        if obj.archived:
            return format_lazy("{} ({})", obj.name, _("archived"))
        return obj.display_name

    def clean(self):
        cleaned = super().clean()
        name = (cleaned.get("name") or "").strip()
        # Resolve the course DEFENSIVELY: Django runs clean() even after a field
        # failed, and add_error deletes that key from cleaned_data — so in the
        # very scenario this form gates (a CA posting an unowned course) there is
        # no "course" key at all and cleaned_data["course"] would KeyError → 500.
        # Resolve to an ID, never a mixed type (cleaned_data holds a Course
        # instance; the fallback is an int) — every comparison below is id-to-id.
        posted_course = cleaned.get("course")
        course_id = posted_course.pk if posted_course else self.instance.course_id
        if not (name and course_id):
            return cleaned
        # Case-insensitive dedup, ARCHIVED ROWS INCLUDED: uniq_allocation_course_name
        # is case-sensitive and has no archived condition, so an archived "Klasy"
        # still owns that slot and would raise IntegrityError in save().
        clash = Allocation.objects.filter(course_id=course_id, name__iexact=name)
        if self.instance.pk is not None:
            clash = clash.exclude(pk=self.instance.pk)
        clash = clash.first()
        if clash is not None:
            if clash.archived:
                self.add_error(
                    "name",
                    _(
                        "An archived allocation with this name already exists on this"
                        " course — un-archive it to reuse the name."
                    ),
                )
            else:
                self.add_error(
                    "name",
                    _("An allocation with this name already exists on this course."),
                )
        return cleaned
