from django.contrib import admin

from institution.models import BrandColor
from institution.models import Institution


class BrandColorInline(admin.TabularInline):
    model = BrandColor
    extra = 0


@admin.register(Institution)
class InstitutionAdmin(admin.ModelAdmin):
    inlines = [BrandColorInline]
