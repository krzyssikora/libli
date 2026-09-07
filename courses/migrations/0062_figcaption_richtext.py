"""Image captions become rich text: widen the column, then escape what is in it.

Every caption stored before this migration is PLAIN TEXT. It was written through
a plain <input type="text"> and rendered with `{{ el.figcaption }}`, which
escaped it on the way out. From here the column is read as HTML (`|safe`), so
the stored bytes have to change meaning to keep the same appearance.

Order is load-bearing. The AlterField comes FIRST because escaping can grow a
value past the old varchar(255) -- one `&` costs four more characters, and a
caption sitting at the 255-character limit would raise DataError mid-migration.

The escape is `html.escape(..., quote=False)`: `&`, `<` and `>` change meaning
in text content and must be escaped; `"` does not, and escaping it would put a
literal `&quot;` in front of every reader. Leaving `<` alone would be worse than
cosmetic -- nh3 reads `<` followed by a letter as a tag that never closes and
drops everything after it, so the author's next save would silently truncate a
caption like `\\(a<b\\)` to `\\(a`.

Reversible on purpose (contrast the RunPython.noop cases elsewhere): escaping is
information-preserving, so an operator rolling back to 0061 gets their bytes
back.
"""

import html

from django.db import migrations
from django.db import models

BATCH = 500


def _rewrite(apps, transform):
    ImageElement = apps.get_model("courses", "ImageElement")
    rows = ImageElement.objects.exclude(figcaption="").only("pk", "figcaption")
    batch = []
    for row in rows.iterator(chunk_size=BATCH):
        row.figcaption = transform(row.figcaption)
        batch.append(row)
        if len(batch) >= BATCH:
            ImageElement.objects.bulk_update(batch, ["figcaption"])
            batch.clear()
    if batch:
        ImageElement.objects.bulk_update(batch, ["figcaption"])


def escape_plain_text(apps, schema_editor):
    _rewrite(apps, lambda v: html.escape(v, quote=False))


def unescape_to_plain_text(apps, schema_editor):
    _rewrite(apps, html.unescape)


class Migration(migrations.Migration):
    dependencies = [
        ("courses", "0061_mediaasset_source_url"),
    ]

    operations = [
        migrations.AlterField(
            model_name="imageelement",
            name="figcaption",
            field=models.TextField(blank=True),
        ),
        migrations.RunPython(escape_plain_text, unescape_to_plain_text),
    ]
