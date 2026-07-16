from django.db import migrations
from django.db import models

from courses.migrations._state_rekey import backward_state
from courses.migrations._state_rekey import forward_state


def forwards(apps, schema_editor):
    UnitProgress = apps.get_model("courses", "UnitProgress")
    for up in UnitProgress.objects.all().iterator():
        up.element_state = forward_state(apps, up.unit_id, up.checklist_state or {})
        up.save(update_fields=["element_state"])


def backwards(apps, schema_editor):
    UnitProgress = apps.get_model("courses", "UnitProgress")
    for up in UnitProgress.objects.all().iterator():
        up.checklist_state = backward_state(apps, up.element_state or {})
        up.save(update_fields=["checklist_state"])


class Migration(migrations.Migration):
    dependencies = [("courses", "0049_guessnumberelement_alter_element_content_type")]

    operations = [
        migrations.AddField(
            model_name="unitprogress",
            name="element_state",
            field=models.JSONField(default=dict),
        ),
        migrations.RunPython(forwards, backwards),
        migrations.RemoveField(model_name="unitprogress", name="checklist_state"),
    ]
