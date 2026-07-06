from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("courses", "0029_backfill_geogebra_urls"),
    ]

    operations = [
        migrations.AddField(
            model_name="iframeelement",
            name="width",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="iframeelement",
            name="height",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
