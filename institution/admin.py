from django.contrib import admin

from institution.models import BrandColor
from institution.models import Institution
from institution.models import PublicPage


class BrandColorInline(admin.TabularInline):
    model = BrandColor
    extra = 0


@admin.register(Institution)
class InstitutionAdmin(admin.ModelAdmin):
    inlines = [BrandColorInline]


@admin.register(PublicPage)
class PublicPageAdmin(admin.ModelAdmin):
    list_display = ("slug", "language", "updated_at")
    list_filter = ("slug", "language")
