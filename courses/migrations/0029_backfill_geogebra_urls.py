from django.db import migrations

# Direct import is deliberate — single source of truth. Do NOT rename/move
# canonicalize_geogebra_url without updating (or squashing) this migration,
# or a fresh-DB replay (CI) will break.
from courses.geogebra import canonicalize_geogebra_url


def forwards(apps, schema_editor):
    IframeElement = apps.get_model("courses", "IframeElement")
    for row in IframeElement.objects.all().iterator():
        new_url = canonicalize_geogebra_url(row.url)
        if new_url != row.url:
            row.url = new_url
            row.save(update_fields=["url"])


def backwards(apps, schema_editor):
    # Not reversible (the original share URL is lost); intentional no-op so the
    # migration can still be unapplied.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("courses", "0028_extend_element_models"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
