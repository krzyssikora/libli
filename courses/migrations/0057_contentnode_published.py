from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    """Two operations, deliberately.

    AddField(default=True) BACKFILLS every existing row as published --
    that is the whole point of the pair. Django then DROPS the database
    default, so new rows take their value from models.py.

    AlterField(default=False) writes nothing to the database. It reconciles
    migration state with models.py so `makemigrations --check` (a CI gate
    since #204) stays clean.

    Collapsing these into one AddField(default=False) blacks out every
    course in every existing database. See the spec, section 1.
    """

    dependencies = [("courses", "0056_alter_calloutelement_kind")]

    operations = [
        migrations.AddField(
            model_name="contentnode",
            name="published",
            field=models.BooleanField(default=True),
        ),
        migrations.AlterField(
            model_name="contentnode",
            name="published",
            field=models.BooleanField(default=False),
        ),
    ]
