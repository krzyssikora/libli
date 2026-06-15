from django.contrib import admin

from courses.models import ContentNode
from courses.models import Course
from courses.models import Subject


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("title", "slug")
    search_fields = ("title",)
    prepopulated_fields = {"slug": ("title",)}


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "language", "visibility")
    list_filter = ("language", "visibility")
    search_fields = ("title",)
    prepopulated_fields = {"slug": ("title",)}
    autocomplete_fields = ("subject", "owner")


@admin.register(ContentNode)
class ContentNodeAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "kind", "unit_type", "obligatory", "order")
    list_filter = ("course", "kind", "unit_type")
    search_fields = ("title",)
    autocomplete_fields = ("course", "parent")
