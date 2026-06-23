from django.conf import settings
from django.db import migrations
from django.db.models import Q

STAFF_ROLE_NAMES = ["Teacher", "Course Admin", "Platform Admin"]


def forwards(apps, schema_editor):
    CohortMembership = apps.get_model("grouping", "CohortMembership")
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    staff_q = (
        Q(is_staff=True) | Q(is_superuser=True) | Q(groups__name__in=STAFF_ROLE_NAMES)
    )
    staff_ids = list(
        User.objects.filter(staff_q).values_list("pk", flat=True).distinct()
    )
    CohortMembership.objects.filter(user_id__in=staff_ids).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("grouping", "0002_default_cohort_backfill"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
