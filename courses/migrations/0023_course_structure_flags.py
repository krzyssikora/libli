from django.db import migrations
from django.db import models

from courses.structure_backfill import backfill_structure_flags


def _forward(apps, schema_editor):
    Course = apps.get_model("courses", "Course")
    ContentNode = apps.get_model("courses", "ContentNode")
    backfill_structure_flags(Course, ContentNode)


def _reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("courses", "0022_questionresponse_review_feedback")]

    operations = [
        migrations.AddField(
            model_name="course",
            name="uses_parts",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="course",
            name="uses_chapters",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="course",
            name="uses_sections",
            field=models.BooleanField(default=True),
        ),
        migrations.RunPython(_forward, _reverse),
    ]
