from django.conf import settings
from django.db import migrations


def forwards(apps, schema_editor):
    Cohort = apps.get_model("grouping", "Cohort")
    CohortMembership = apps.get_model("grouping", "CohortMembership")
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))

    default, _ = Cohort.objects.get_or_create(
        slug="default",
        defaults={"name": "Default", "is_default": True},
    )
    if not default.is_default:
        default.is_default = True
        default.save(update_fields=["is_default"])

    for user in User.objects.all():
        CohortMembership.objects.get_or_create(
            user=user, defaults={"cohort": default}
        )


def backwards(apps, schema_editor):
    Cohort = apps.get_model("grouping", "Cohort")
    Cohort.objects.filter(slug="default", is_default=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("grouping", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [migrations.RunPython(forwards, backwards)]
