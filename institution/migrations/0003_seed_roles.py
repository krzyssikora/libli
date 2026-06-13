from django.db import migrations


def forwards(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for name in ["Student", "Teacher", "Course Admin", "Platform Admin"]:
        Group.objects.get_or_create(name=name)


def backwards(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(
        name__in=["Student", "Teacher", "Course Admin", "Platform Admin"]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("institution", "0002_seed_branding"),
        ("auth", "0001_initial"),  # Group model exists since auth's first migration (version-stable)
    ]
    operations = [migrations.RunPython(forwards, backwards)]
