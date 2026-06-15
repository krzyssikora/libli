from django.core.exceptions import ValidationError

from courses.models import ContentNode
from courses.models import Element


def move_in_list(siblings, item, direction):
    """`siblings`: instances in effective (order, pk) order. Return a new list with
    `item` shifted one slot in `direction`, or None for a boundary no-op."""
    ids = [s.pk for s in siblings]
    i = ids.index(item.pk)
    j = i - 1 if direction == "up" else i + 1
    if j < 0 or j >= len(siblings):
        return None
    new = list(siblings)
    new[i], new[j] = new[j], new[i]
    return new


def assign_orders_nodes(ordered):
    """Renumber 0..n; save only rows whose order changed, bumping `updated`."""
    for idx, node in enumerate(ordered):
        if node.order != idx:
            node.order = idx
            node.save(update_fields=["order", "updated"])


def assign_orders_elements(ordered):
    for idx, el in enumerate(ordered):
        if el.order != idx:
            el.order = idx
            el.save(update_fields=["order"])


def compact_nodes(course, parent_id):
    siblings = list(
        ContentNode.objects.filter(course=course, parent_id=parent_id).order_by(
            "order", "pk"
        )
    )
    assign_orders_nodes(siblings)


def compact_elements(unit):
    els = list(Element.objects.filter(unit=unit).order_by("order", "pk"))
    assign_orders_elements(els)


def place_node(node, new_parent, course, position):
    """Insert `node` into the destination scope at a 0-based `position` (clamped
    0..N), renumbering destination siblings to distinct orders.

    Saves `node` (full save → parent+order+updated) and every changed sibling.

    **Precondition:** caller must set ``node.parent = new_parent`` (and save the
    in-memory attribute) *before* calling this function.  The assertion below
    detects violations at call time; without it, a mismatched parent would be
    silently persisted to the database on the full ``node.save()`` below.
    """
    assert node.parent_id == (new_parent.pk if new_parent is not None else None), (
        "place_node: caller must set node.parent before calling"
    )
    others = list(
        ContentNode.objects.filter(course=course, parent=new_parent)
        .exclude(pk=node.pk)
        .order_by("order", "pk")
    )
    if position is None or position > len(others):
        position = len(others)
    if position < 0:
        position = 0
    ordered = others[:position] + [node] + others[position:]
    for idx, n in enumerate(ordered):
        if n.pk == node.pk:
            n.order = idx
            n.save()  # full save: persists the new parent + order; bumps updated
        elif n.order != idx:
            n.order = idx
            n.save(update_fields=["order", "updated"])


def assert_not_descendant(node, candidate_parent):
    """Raise ValidationError if `candidate_parent` is `node` itself or one of its
    descendants (would create a cycle). Walks up from the candidate."""
    cur = candidate_parent
    while cur is not None:
        if cur.pk == node.pk:
            raise ValidationError(
                "Cannot move a node under itself or its own descendant."
            )
        cur = cur.parent
