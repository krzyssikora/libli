from django.contrib import admin

from courses.models import ContentNode
from courses.models import Course
from courses.models import Element
from courses.models import Enrollment
from courses.models import IframeElement
from courses.models import ImageElement
from courses.models import MathElement
from courses.models import Subject
from courses.models import TextElement
from courses.models import UnitProgress
from courses.models import VideoElement


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("title_en", "title_pl", "slug")
    search_fields = ("title_en", "title_pl")
    prepopulated_fields = {"slug": ("title_en",)}


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "language", "visibility")
    list_filter = ("language", "visibility")
    search_fields = ("title",)
    prepopulated_fields = {"slug": ("title",)}
    autocomplete_fields = ("subjects", "owner")


@admin.register(ContentNode)
class ContentNodeAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "kind", "unit_type", "obligatory", "order")
    list_filter = ("course", "kind", "unit_type")
    search_fields = ("title",)
    autocomplete_fields = ("course", "parent")


# Only the original handful of simple content types are registered here; every
# element type added since (HtmlElement, all question types, SlideBreakElement)
# is intentionally left off this list — elements are authored/managed exclusively
# through the builder UI (courses/views_manage.py), and this pre-existing debug
# registry was never extended to cover them. Not extending it for
# SlideBreakElement keeps it consistent with that established (if imperfect)
# pattern rather than singling the new type out.
admin.site.register(TextElement)
admin.site.register(ImageElement)
admin.site.register(VideoElement)
admin.site.register(IframeElement)
admin.site.register(MathElement)


@admin.register(Element)
class ElementAdmin(admin.ModelAdmin):
    list_display = ("pk", "unit", "content_type", "object_id", "order")
    list_filter = ("content_type",)
    autocomplete_fields = ("unit",)


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ("student", "course", "source", "created_at")
    list_filter = ("source", "course")
    autocomplete_fields = ("student", "course")


@admin.register(UnitProgress)
class UnitProgressAdmin(admin.ModelAdmin):
    list_display = ("student", "unit", "completed", "completed_at")
    list_filter = ("completed",)
    autocomplete_fields = ("student", "unit")
