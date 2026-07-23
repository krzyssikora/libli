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
    # An existing node KEEPS its title: a manual rename in the editor (chapters
    # seed as "__PLACEHOLDER chapter N__") is user-owned and must survive an
    # idempotent reload. The manifest title only seeds a node on first create.
    # unit_type is structural (lesson/quiz), not user-edited, so keep it in sync.
    if node.unit_type != unit_type:
        node.unit_type = unit_type
        node.save(update_fields=["unit_type"])
    return node


def prune_orphans(course, parent, keep_count):
    stale = ContentNode.objects.filter(
        course=course, parent=parent, order__gte=keep_count
    )
    for node in stale:
        node.delete()  # ContentNode.delete sweeps element content objects too


def rebuild_unit_elements(
    course, unit, element_dicts, *, source_root, source_dir, allow_html, missing=None
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
            missing=missing,
        )
