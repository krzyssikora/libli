from django import forms
from django.db import IntegrityError
from django.db import transaction
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


class AllocationChoiceIterator(forms.models.ModelChoiceIterator):
    """Groups allocation options into one <optgroup> per course.

    Two things here are load-bearing:
      * the empty choice is yielded FIRST and outside any optgroup — the base
        __iter__ is what normally emits it, so a subclass that yields only
        optgroups silently drops "— none —" and leaves no way to detach a group;
      * labels go through self.field.label_from_instance, which is where the
        "(archived)" suffix lives. Yielding obj.name would defeat that override
        for THIS field while `cohorts` (stock iterator) kept showing its suffix.
    """

    def __iter__(self):
        if self.field.empty_label is not None:
            yield ("", self.field.empty_label)
        # Keyed on course_id, NOT title: Course.title is a plain CharField with
        # no unique constraint, and two same-titled courses merging into one
        # optgroup would give it options carrying different data-course values —
        # which the client filter hides wholesale, taking valid options with it.
        by_course = {}
        for obj in self.queryset:
            title, options = by_course.setdefault(obj.course_id, (obj.course.title, []))
            options.append((self.choice(obj)[0], self.field.label_from_instance(obj)))
        for title, options in by_course.values():
            yield (title, options)


class AllocationSelect(forms.Select):
    """Adds data-course to each real <option> so the create form's client-side
    filter can narrow allocations to the chosen course. Per-option attributes are
    only reachable from create_option — a choices tuple carries value and label
    only."""

    def create_option(self, name, value, label, selected, index, **kwargs):
        option = super().create_option(name, value, label, selected, index, **kwargs)
        # Select.optgroups calls this for the empty choice too, passing a bare
        # "" rather than a ModelChoiceIteratorValue — an unguarded
        # value.instance would AttributeError on every render.
        instance = getattr(value, "instance", None)
        if instance is not None:
            option["attrs"]["data-course"] = str(instance.course_id)
        return option


class GroupForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ["name", "course", "teachers", "external_id", "allocation"]
        widgets = {"teachers": forms.CheckboxSelectMultiple}
        labels = {
            "name": _("Name"),
            "course": _("Course"),
            "teachers": _("Teachers"),
            "external_id": _("Register class code"),
            "allocation": _("Allocation"),
        }
        help_texts = {"external_id": _("Class code in your external register.")}

    new_allocation = forms.CharField(
        max_length=200,  # matches Allocation.name; without it a long value 500s
        required=False,
        label=_("…or create a new allocation"),
    )

    _resolved_allocation = None  # class default: save() must not AttributeError

    def __init__(self, *args, user=None, **kwargs):
        self._user = user
        super().__init__(*args, **kwargs)
        if self.instance.pk is not None:
            # Course is immutable after creation; lock the widget.
            self.fields["course"].disabled = True
        from grouping.services import teacher_users

        self.fields["teachers"].queryset = teacher_users()

        field = self.fields["allocation"]
        field.empty_label = _("— none —")
        field.label_from_instance = self._allocation_label
        # The iterator MUST be assigned before the queryset: _set_queryset ends
        # with `self.widget.choices = self.choices`, so the widget captures
        # whichever iterator exists at assignment time. Assigning it afterwards
        # leaves the WIDGET on the base iterator (flat options, no optgroups)
        # while field.choices still looks correct.
        field.iterator = AllocationChoiceIterator
        # The hook MUST be set here: `{{ form.allocation }}` renders the widget
        # as-is, Django templates cannot add attributes to a rendered widget, and
        # this repo has no widget_tweaks. Without it initAllocationFilter() finds
        # nothing and is silently inert.
        field.widget = AllocationSelect(attrs={"data-allocation-select": ""})
        if self.instance.pk:
            base = Q(course=self.instance.course)
        elif user is not None:
            base = Q(course__in=manageable_courses(user))
        else:
            base = Q(pk__in=[])
        field.queryset = (
            Allocation.objects.filter(
                (base & Q(archived=False)) | Q(pk=self.instance.allocation_id)
            )
            .select_related("course")
            .order_by("course__title", "name")
        )

    @staticmethod
    def _allocation_label(obj):
        if obj.archived:
            return format_lazy("{} ({})", obj.name, _("archived"))
        return obj.name

    def clean(self):
        cleaned = super().clean()
        # Defensive resolve — add_error deletes a failed field's key, and clean()
        # still runs. cleaned_data["course"] would KeyError.
        #
        # Resolve to an ID, never a mixed type: `cleaned.get("course")` is a
        # Course instance while `self.instance.course_id` is an int, so comparing
        # `picked.course_id != course.pk` would AttributeError on the fallback
        # branch — turning the specified 200 re-render into a 500. Every
        # comparison below is id-to-id.
        posted_course = cleaned.get("course")
        course_id = posted_course.pk if posted_course else self.instance.course_id
        picked = cleaned.get("allocation")
        new_name = (cleaned.get("new_allocation") or "").strip()

        if new_name:
            # The select ECHOES the current allocation back on every edit-form
            # POST, so only a genuinely DIFFERENT pick counts as a conflict.
            picked_id = picked.pk if picked is not None else None
            if picked_id is not None and picked_id != self.instance.allocation_id:
                self.add_error(
                    "new_allocation",
                    _("Choose an existing allocation or type a new name, not both."),
                )
                return cleaned
            # The new name wins: clear the echoed value so construct_instance and
            # save()'s fallback both see None and the create branch actually runs.
            cleaned["allocation"] = None
            picked = None
            if course_id:
                clash = Allocation.objects.filter(
                    course_id=course_id, name__iexact=new_name
                ).first()
                if clash is not None and clash.archived:
                    self.add_error(
                        "new_allocation",
                        _(
                            "An archived allocation with this name already exists on"
                            " this course — un-archive it to reuse the name."
                        ),
                    )
                    return cleaned
                self._resolved_allocation = clash

        if picked is not None and course_id and picked.course_id != course_id:
            # Field error, not a non-field one: group_form.html renders errors
            # per field, so a non-field error would be invisible.
            self.add_error(
                "allocation", _("This allocation belongs to a different course.")
            )
        return cleaned

    def save(self, commit=True):
        # commit is accepted for signature compatibility; GroupForm always
        # commits (both views call it plainly).
        course = self.cleaned_data.get("course") or self.instance.course
        name = (self.cleaned_data.get("new_allocation") or "").strip()
        # The picked path must seed this too — clean() stashes
        # _resolved_allocation only on the new_allocation path, so without the
        # fallback the assignment below would null a picked allocation.
        allocation = self._resolved_allocation or self.cleaned_data.get("allocation")
        if allocation is None and name:
            try:
                with transaction.atomic():  # savepoint: absorb a concurrent create
                    allocation = Allocation.objects.create(course=course, name=name)
            except IntegrityError:
                allocation = Allocation.objects.get(course=course, name=name)
        group = super().save(commit=False)
        group.allocation = allocation
        group.save()
        self.save_m2m()
        return group


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
