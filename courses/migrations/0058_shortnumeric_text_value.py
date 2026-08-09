"""Convert ShortNumericQuestionElement.value/tolerance from numeric(20,8) to text.

ROLLING THIS BACK MEANS RESTORING A DATABASE BACKUP, not running `migrate`
backwards. The reverse_code below is RunPython.noop, which does NOT mean the
migration is safely reversible:

- The data is never reconstructed. 1/3 has no Decimal form, so reversing invents
  nothing rather than guessing.
- Reversing with rows present fails at the database layer anyway: the RemoveField
  reverse re-adds `value` as a non-null DecimalField with no default.

noop rather than an omitted reverse_code is a TESTABILITY requirement, not a
convenience. Migration.unapply() checks operation.reversible for every operation
and raises IrreversibleError BEFORE running any of them
(django/db/migrations/migration.py:153). Since pytest-django builds the test DB at
the leaf, a truly irreversible migration cannot be unapplied to create old-schema
rows — which would leave the data conversion, including the str()/E-notation trap
that would NULL every zero-tolerance row, completely untested.
"""

from decimal import Decimal
from decimal import localcontext

from django.db import migrations
from django.db import models

import courses.marking

BATCH = 500


def _format_decimal_plain(value):
    """FROZEN copy of courses.marking.format_decimal_plain.

    Deliberately not imported. A migration must keep doing what it did the day it
    shipped; importing live helpers means a later change to the precision or the
    storage cap retroactively alters what 0058 does on a fresh deploy. prec is
    hard-coded because MAX_STORED_NUMERIC_CHARS is equally forbidden to import; the
    old column is numeric(20,8), so 80 is far more than sufficient.
    """
    with localcontext() as ctx:
        ctx.prec = 80
        return format(Decimal(value).normalize(), "f")


def forwards(apps, schema_editor):
    Element = apps.get_model("courses", "ShortNumericQuestionElement")

    # Counting pass FIRST. A negative tolerance canonicalises to None, and writing
    # NULL into a non-null column would raise IntegrityError partway through an
    # IRREVERSIBLE production migration. Abort before any write so the operator
    # repairs the data deliberately. RuntimeError, not CommandError: this must fail
    # identically under `manage.py migrate` and under pytest.
    negative = list(
        Element.objects.filter(tolerance__lt=0).values_list("pk", flat=True)[:50]
    )
    if negative:
        raise RuntimeError(
            "Cannot migrate: ShortNumericQuestionElement rows have a negative "
            f"tolerance (pks: {negative}). Repair them before running 0058."
        )

    batch = []
    for row in Element.objects.all().iterator(chunk_size=BATCH):
        # Operate on the Decimal DIRECTLY. str(Decimal("0.00000000")) is '0E-8' —
        # E-notation, which the grammars reject — so routing these through a text
        # canonicaliser would return None for EVERY zero tolerance and every value
        # below 1e-6, i.e. most rows.
        row.value_text = _format_decimal_plain(row.value)
        if row.tolerance == 0:
            row.tolerance_text = ""
        elif row.tolerance < 0:
            # Unreachable: the counting pass aborted. Belt-and-braces.
            raise RuntimeError(f"negative tolerance survived the counting pass: pk={row.pk}")
        else:
            row.tolerance_text = _format_decimal_plain(row.tolerance)
        if row.value_text is None or row.tolerance_text is None:
            # Unreachable by construction today: _format_decimal_plain always returns
            # a str, and the zero branch above assigns "". Kept as a cheap backstop
            # against a future edit to either path, not as live coverage — don't
            # mistake this for a branch a test can exercise as written.
            raise RuntimeError(f"refusing to write NULL for pk={row.pk}")
        batch.append(row)
        # Accumulate and FLUSH. batch_size bounds rows per statement, not Python
        # objects held, so a single terminal bulk_update would hold every row.
        if len(batch) >= BATCH:
            Element.objects.bulk_update(batch, ["value_text", "tolerance_text"])
            batch.clear()
    if batch:
        Element.objects.bulk_update(batch, ["value_text", "tolerance_text"])


class Migration(migrations.Migration):
    dependencies = [("courses", "0057_contentnode_published")]

    operations = [
        migrations.AddField(
            model_name="shortnumericquestionelement",
            name="value_text",
            field=models.CharField(default="", max_length=64),
        ),
        migrations.AddField(
            model_name="shortnumericquestionelement",
            name="tolerance_text",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
        migrations.RemoveField(model_name="shortnumericquestionelement", name="value"),
        migrations.RemoveField(model_name="shortnumericquestionelement", name="tolerance"),
        migrations.RenameField(
            model_name="shortnumericquestionelement",
            old_name="value_text",
            new_name="value",
        ),
        migrations.RenameField(
            model_name="shortnumericquestionelement",
            old_name="tolerance_text",
            new_name="tolerance",
        ),
        migrations.AlterField(
            model_name="shortnumericquestionelement",
            name="value",
            field=models.CharField(
                max_length=64, validators=[courses.marking.validate_numeric_text]
            ),
        ),
        migrations.AlterField(
            model_name="shortnumericquestionelement",
            name="tolerance",
            field=models.CharField(
                blank=True,
                default="",
                max_length=64,
                validators=[courses.marking.validate_tolerance_text],
            ),
        ),
    ]
