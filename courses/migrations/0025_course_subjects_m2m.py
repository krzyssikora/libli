from django.db import migrations, models


def backfill_subjects(apps, schema_editor):
    Course = apps.get_model("courses", "Course")
    # Forward accessor on the field `subjects` (stable name); only the reverse
    # related_name is temporary. Never use the ambiguous reverse subject.courses.
    for course in Course.objects.exclude(subject__isnull=True):
        course.subjects.add(course.subject_id)


def reverse_backfill(apps, schema_editor):
    Course = apps.get_model("courses", "Course")
    for course in Course.objects.all():
        first = course.subjects.first()
        if first is not None:
            course.subject_id = first.pk
            course.save(update_fields=["subject"])


class Migration(migrations.Migration):
    dependencies = [("courses", "0024_subject_localize_title")]

    operations = [
        # 1. Add the M2M under a TEMPORARY related_name so it doesn't clash with
        #    the FK's related_name="courses" while both coexist (fields.E304).
        migrations.AddField(
            "course",
            "subjects",
            models.ManyToManyField(
                blank=True, related_name="courses_m2m", to="courses.subject"
            ),
        ),
        # 2. Backfill from the old FK (still present).
        migrations.RunPython(backfill_subjects, reverse_backfill),
        # 3. Drop the FK, freeing the "courses" reverse name.
        migrations.RemoveField("course", "subject"),
        # 4. Rename the M2M's reverse to the final "courses" (DB no-op).
        migrations.AlterField(
            "course",
            "subjects",
            models.ManyToManyField(
                blank=True, related_name="courses", to="courses.subject"
            ),
        ),
    ]
