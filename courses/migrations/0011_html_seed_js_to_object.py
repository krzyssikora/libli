import re

from django.db import migrations

# The seed field changed meaning: it used to hold a full JS statement
# (``window.SEED = {...};``); it now holds just the object literal, which the
# server wraps as ``window.SEED = (...);``. Convert any existing statement-form
# value down to the bare object so it is not double-wrapped.
_STMT = re.compile(r"^\s*window\.SEED\s*=\s*(.*?);?\s*$", re.DOTALL)


def to_object(apps, schema_editor):
    ContentNode = apps.get_model("courses", "ContentNode")
    for node in ContentNode.objects.exclude(html_seed_js=""):
        m = _STMT.match(node.html_seed_js)
        if m:
            node.html_seed_js = m.group(1).strip()
            node.save(update_fields=["html_seed_js"])


def noop(apps, schema_editor):
    # One-way data shape; the bare object remains valid input going forward.
    pass


class Migration(migrations.Migration):
    dependencies = [("courses", "0010_htmlelement_and_html_fields")]
    operations = [migrations.RunPython(to_object, noop)]
