from django.db import migrations

from courses.migrations_support import body_is_empty_ish

# Inlined, NEVER imported from the live model: a migration must not depend on
# today's value of a constant. Documents the historical slot literal only --
# NOT used as a filter below, which groups children by `parent` alone (see the
# comment at the child_ids query), mirroring resolved_children()'s handling of
# a single-slot container.
SLOT_ID = "only"


def clear_unreachable_bodies(apps, schema_editor):
    """Clear a spoiler `body` that is empty-ish (A) or an exact duplicate of one of
    its child TextElements (B). Anything else (C) is LEFT ALONE, so genuinely
    stranded content reappears above the children -- the correct outcome.

    Row filter is EVERY bodied spoiler, not only those with children: ~12 rows in
    libli carry a body and none, and the moment an author adds a child an empty-ish
    body would start rendering as a blank paragraph. Category A is safe to clear
    regardless of children; category B is only evaluated where children exist.
    """
    ContentType = apps.get_model("contenttypes", "ContentType")
    Element = apps.get_model("courses", "Element")
    SpoilerElement = apps.get_model("courses", "SpoilerElement")
    TextElement = apps.get_model("courses", "TextElement")

    try:
        sp_ct = ContentType.objects.get(app_label="courses", model="spoilerelement")
        text_ct = ContentType.objects.get(app_label="courses", model="textelement")
    except ContentType.DoesNotExist:
        return

    for sp in SpoilerElement.objects.exclude(body=""):
        if body_is_empty_ish(sp.body):
            SpoilerElement.objects.filter(pk=sp.pk).update(body="")
            continue

        join = (
            Element.objects.filter(content_type=sp_ct, object_id=sp.pk)
            .order_by("pk")
            .first()
        )
        if join is None:
            continue
        # `parent` ALONE, no tab_id filter -- mirrors resolved_children(), whose
        # docstring says the single slot makes tab_id unnecessary. A narrower filter
        # would let a drifted-tab_id child render (duplicating the body) while
        # staying invisible to this check.
        child_ids = Element.objects.filter(
            parent=join, content_type=text_ct
        ).values_list("object_id", flat=True)
        if TextElement.objects.filter(pk__in=list(child_ids), body=sp.body).exists():
            SpoilerElement.objects.filter(pk=sp.pk).update(body="")


def noop_reverse(apps, schema_editor):
    """Documented no-op: the migration only cleared fields that were unreachable."""


class Migration(migrations.Migration):
    # Keep the `dependencies` line `makemigrations --empty` generated and replace only
    # `operations`. At time of writing the latest is 0052_alter_calloutelement_kind, so
    # this file is 0053_spoiler_body_cleanup — verified via `makemigrations --empty`.
    dependencies = [("courses", "0052_alter_calloutelement_kind")]
    operations = [migrations.RunPython(clear_unreachable_bodies, noop_reverse)]
