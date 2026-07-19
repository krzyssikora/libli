"""Positional node upsert, orphan prune, and per-unit element rebuild."""

from courses.lal_loader.builders import build_element
from courses.models import ContentNode
from courses.models import Element
from courses.models import _delete_element_content_objects


def upsert_node(course, parent, order, kind, title, unit_type=None):
    node = ContentNode.objects.filter(
        course=course, parent=parent, order=order, kind=kind
    ).first()
    if node is None:
        return ContentNode.objects.create(
            course=course,
            parent=parent,
            order=order,
            kind=kind,
            title=title,
            unit_type=unit_type,
        )
    node.title = title
    node.unit_type = unit_type
    node.save(update_fields=["title", "unit_type"])
    return node


def prune_orphans(course, parent, keep_count):
    stale = ContentNode.objects.filter(
        course=course, parent=parent, order__gte=keep_count
    )
    for node in stale:
        node.delete()  # ContentNode.delete sweeps element content objects too


def rebuild_unit_elements(
    course, unit, element_dicts, *, source_root, source_dir, allow_html
):
    rows = Element.objects.filter(unit=unit)
    _delete_element_content_objects(rows)  # delete concrete rows first (no orphans)
    rows.delete()  # then the join rows
    for el in element_dicts:
        build_element(
            course,
            unit,
            el,
            source_root=source_root,
            source_dir=source_dir,
            allow_html=allow_html,
        )
