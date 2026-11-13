from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import gettext_lazy as _

from accounts.forms import CourseGroupChoiceField
from accounts.forms import course_group_queryset
from accounts.invitations import build_accept_url
from accounts.models import Invitation
from accounts.models import User


class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("libli", {"fields": ("display_name", "language", "theme")}),
    )


admin.site.register(User, CustomUserAdmin)


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = (
        "email",
        "role",
        "group_display",
        "invited_by",
        "created_at",
        "expires_at",
        "accepted_at",
    )
    list_select_related = ("invited_by", "group__course")
    readonly_fields = ("token", "created_at", "accepted_at", "accept_url")
    fields = (
        "email",
        "role",
        "group",
        "invited_by",
        "expires_at",
        "token",
        "accept_url",
        "created_at",
        "accepted_at",
    )

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        form.base_fields["group"] = CourseGroupChoiceField(
            queryset=course_group_queryset(include_pk=obj.group_id if obj else None),
            required=False,
            label=_("Group"),
            empty_label=_("— no group —"),
        )
        return form

    @admin.display(description=_("Group"))
    def group_display(self, obj):
        if obj.group is None:
            return ""
        return f"{obj.group.name} — {obj.group.course.title}"

    @admin.display(description="Accept URL")
    def accept_url(self, obj):
        if not obj.pk:
            return "(available after saving)"
        return build_accept_url(obj)
