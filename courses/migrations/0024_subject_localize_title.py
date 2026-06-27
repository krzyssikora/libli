from django.db import migrations, models


def copy_title_to_en(apps, schema_editor):
    Subject = apps.get_model("courses", "Subject")
    for s in Subject.objects.all():
        s.title_en = s.title
        s.save(update_fields=["title_en"])


def reverse_copy(apps, schema_editor):
    Subject = apps.get_model("courses", "Subject")
    for s in Subject.objects.all():
        s.title = s.title_en
        s.save(update_fields=["title"])


class Migration(migrations.Migration):
    dependencies = [("courses", "0023_course_structure_flags")]

    operations = [
        migrations.AddField(
            "subject",
            "title_en",
            models.CharField(default="", max_length=200),
            preserve_default=False,
        ),
        migrations.AddField(
            "subject",
            "title_pl",
            models.CharField(blank=True, default="", max_length=200),
            preserve_default=False,
        ),
        migrations.RunPython(copy_title_to_en, reverse_copy),
        migrations.RemoveField("subject", "title"),
        migrations.AlterModelOptions("subject", options={"ordering": ["title_en"]}),
    ]
