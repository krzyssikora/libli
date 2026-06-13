from django.db import migrations

DEFAULT_COLORS = {"primary": "#147E78", "accent": "#C77B2A"}


def forwards(apps, schema_editor):
    Institution = apps.get_model("institution", "Institution")
    BrandColor = apps.get_model("institution", "BrandColor")
    inst, _ = Institution.objects.get_or_create(pk=1)
    for key, value in DEFAULT_COLORS.items():
        BrandColor.objects.get_or_create(institution=inst, key=key, defaults={"value": value})


def backwards(apps, schema_editor):
    # Destructive by design: removes the primary/accent rows of the singleton.
    BrandColor = apps.get_model("institution", "BrandColor")
    BrandColor.objects.filter(institution_id=1, key__in=DEFAULT_COLORS).delete()


class Migration(migrations.Migration):
    dependencies = [("institution", "0001_initial")]
    operations = [migrations.RunPython(forwards, backwards)]
