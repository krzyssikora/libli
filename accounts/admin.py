from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

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
    list_display = ("email", "invited_by", "created_at", "expires_at", "accepted_at")
    readonly_fields = ("token", "created_at", "accepted_at", "accept_url")
    fields = (
        "email",
        "invited_by",
        "expires_at",
        "token",
        "accept_url",
        "created_at",
        "accepted_at",
    )

    @admin.display(description="Accept URL")
    def accept_url(self, obj):
        if not obj.pk:
            return "(available after saving)"
        return build_accept_url(obj)
