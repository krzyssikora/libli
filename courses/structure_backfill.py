"""Data-migration helper: set each existing course's structure flags from the
content kinds it actually uses, so no in-use level is ever excluded. A course
with zero nodes is skipped, keeping the True/Full default (nothing to infer)."""


def backfill_structure_flags(Course, ContentNode):
    for course in Course.objects.all():
        kinds = set(
            ContentNode.objects.filter(course=course).values_list("kind", flat=True)
        )
        if not kinds:
            continue  # empty course -> keep default (Full)
        course.uses_parts = "part" in kinds
        course.uses_chapters = "chapter" in kinds
        course.uses_sections = "section" in kinds
        course.save(update_fields=["uses_parts", "uses_chapters", "uses_sections"])
