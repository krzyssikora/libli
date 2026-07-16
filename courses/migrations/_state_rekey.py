"""Pure re-key helpers for the checklist_state -> element_state migration.

Extracted so they can be unit-tested directly; the migration passes the historical
app registry in. NEVER import concrete models here.
"""


def _markdone_ct(apps):
    ContentType = apps.get_model("contenttypes", "ContentType")
    return ContentType.objects.filter(
        app_label="courses", model="markdoneelement"
    ).first()


def forward_state(apps, unit_id, old):
    """{"<MarkDoneElement.pk>": [item_pk, ...]} -> {"<Element.pk>": {"items": [...]}}.

    Two shape changes, not one: the KEY moves content-pk -> join-row-pk, and the
    VALUE (a bare list today) is WRAPPED under "items". Orphaned keys are dropped --
    already-dead data the current read path ignores.
    """
    if not isinstance(old, dict):
        return {}
    Element = apps.get_model("courses", "Element")
    ct = _markdone_ct(apps)
    if ct is None:
        return {}
    out = {}
    for key, items in old.items():
        try:
            object_id = int(key)
        except (TypeError, ValueError):
            continue
        if not isinstance(items, list):
            continue
        # The GFK is effectively 1:1 (see TabsElement.join_row); order_by("pk") makes
        # the impossible >1 case deterministic AND identical to what join_row() and
        # the render path resolve to, so migration and runtime agree.
        row = (
            Element.objects.filter(
                content_type=ct, object_id=object_id, unit_id=unit_id
            )
            .order_by("pk")
            .first()
        )
        if row is None:
            continue  # orphan: element deleted
        out[str(row.pk)] = {"items": list(items)}
    return out


def backward_state(apps, new):
    """{"<Element.pk>": {...}} -> {"<MarkDoneElement.pk>": [item_pk, ...]}.

    LOSSY BY NECESSITY, and deliberately so: every non-markdone blob is DROPPED,
    because checklist_state structurally cannot represent it (a revealgate's
    {"open": true} has nowhere to go). Also unwraps "items" back to a bare list.
    """
    if not isinstance(new, dict):
        return {}
    Element = apps.get_model("courses", "Element")
    ct = _markdone_ct(apps)
    if ct is None:
        return {}
    out = {}
    for key, blob in new.items():
        try:
            row_pk = int(key)
        except (TypeError, ValueError):
            continue
        if not isinstance(blob, dict):
            continue
        items = blob.get("items")
        if not isinstance(items, list):
            continue  # not a markdone blob -> drop
        row = Element.objects.filter(pk=row_pk, content_type=ct).first()
        if row is None:
            continue  # not a markdone element -> drop
        out[str(row.object_id)] = list(items)
    return out
