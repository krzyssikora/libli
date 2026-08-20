from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils.text import format_lazy
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

# 'default' is permanently reserved for the system Default cohort's slug.
RESERVED_DEFAULT_SLUG = "default"


class Cohort(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    is_default = models.BooleanField(default=False)
    archived = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["is_default"],
                condition=Q(is_default=True),
                name="uniq_single_default_cohort",
            )
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._generate_slug()
        super().save(*args, **kwargs)

    def _generate_slug(self):
        base = slugify(self.name) or "cohort"
        candidate = base
        n = 1
        # A non-default cohort may never claim the reserved 'default' slug.
        reserved = candidate == RESERVED_DEFAULT_SLUG and not self.is_default
        while (
            reserved
            or Cohort.objects.filter(slug=candidate).exclude(pk=self.pk).exists()
        ):
            n += 1
            candidate = f"{base}-{n}"
            reserved = False
        return candidate

    @property
    def display_name(self):
        # The current default cohort is shown as "<name> (default)" — the name is
        # the real stored value, the parenthetical marker is translatable.
        if self.is_default:
            return format_lazy("{} ({})", self.name, _("default"))
        return self.name

    def __str__(self):
        return self.name


class CohortMembership(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="cohort_membership",
    )
    cohort = models.ForeignKey(
        Cohort, on_delete=models.CASCADE, related_name="memberships"
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    def __str__(self):
        return f"{self.user_id} in cohort {self.cohort_id}"


class Group(models.Model):
    name = models.CharField(max_length=200)
    external_id = models.CharField(max_length=64, blank=True, default="")
    course = models.ForeignKey(
        "courses.Course", on_delete=models.CASCADE, related_name="groups"
    )
    teachers = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="taught_groups"
    )
    allocation = models.ForeignKey(
        "Allocation",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="groups",
    )
    archived = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        # A group's course is immutable after creation (see spec §2).
        if self.pk is not None:
            old_course_id = (
                Group.objects.filter(pk=self.pk)
                .values_list("course_id", flat=True)
                .first()
            )
            if old_course_id is not None and old_course_id != self.course_id:
                raise ValidationError(
                    _("A group's course cannot be changed after creation.")
                )
        # The allocation must be on this group's own course (spec: course
        # scoping). Read the course id WITHOUT dereferencing the FK — touching
        # self.allocation would fetch the row on every Group.save(), including
        # services.set_group_archived's save(update_fields=["archived"]).
        if self.allocation_id is not None:
            alloc_course_id = (
                Allocation.objects.filter(pk=self.allocation_id)
                .values_list("course_id", flat=True)
                .first()
            )
            if alloc_course_id is not None and alloc_course_id != self.course_id:
                raise ValidationError(
                    _("The allocation must belong to the same course as the group.")
                )
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class GroupMembership(models.Model):
    group = models.ForeignKey(
        Group, on_delete=models.CASCADE, related_name="memberships"
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="group_memberships",
    )
    added_at = models.DateTimeField(auto_now_add=True)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["group", "student"], name="uniq_groupmembership_group_student"
            )
        ]

    def __str__(self):
        return f"{self.student_id} in group {self.group_id}"


class Allocation(models.Model):
    """A named grouping of one course's groups that together are meant to
    partition one or more cohorts — e.g. "matematyka, starting 2026". See
    docs/superpowers/specs/2026-08-20-group-allocation-grid-design.md."""

    name = models.CharField(max_length=200)
    course = models.ForeignKey(
        "courses.Course", on_delete=models.CASCADE, related_name="allocations"
    )
    cohorts = models.ManyToManyField(Cohort, blank=True, related_name="allocations")
    archived = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["course", "name"], name="uniq_allocation_course_name"
            )
        ]

    def save(self, *args, **kwargs):
        # Mirror-image of Group.save's guard: an allocation's course may not
        # change once groups are attached, or those groups would silently sit
        # in an allocation on a different course. The form's `disabled` widget
        # is not enough — it is not a model-layer guarantee.
        if self.pk is not None:
            old_course_id = (
                Allocation.objects.filter(pk=self.pk)
                .values_list("course_id", flat=True)
                .first()
            )
            if (
                old_course_id is not None
                and old_course_id != self.course_id
                and self.groups.exists()
            ):
                raise ValidationError(
                    _(
                        "An allocation's course cannot be changed"
                        " once groups are attached."
                    )
                )
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Collection(models.Model):
    name = models.CharField(max_length=200)
    course = models.ForeignKey(
        "courses.Course", on_delete=models.CASCADE, related_name="collections"
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="owned_collections",
    )
    groups = models.ManyToManyField(Group, related_name="collections")
    archived = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        # course is immutable once ANY group is attached (parity with the M2M
        # guard) — the guard triggers on "any groups attached", independent of
        # whether the new course would match those groups.
        if self.pk is not None:
            old_course_id = (
                Collection.objects.filter(pk=self.pk)
                .values_list("course_id", flat=True)
                .first()
            )
            if (
                old_course_id is not None
                and old_course_id != self.course_id
                and self.groups.exists()
            ):
                raise ValidationError(
                    _(
                        "A collection's course cannot be changed"
                        " once groups are attached."
                    )
                )
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name
