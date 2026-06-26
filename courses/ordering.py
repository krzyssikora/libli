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


def place_element(element, unit, position):
    """Insert `element` at a 0-based `position` among the unit's other elements
    (clamped 0..len(others)), renumbering only rows whose order changed. Returns
    True iff any order changed. `others` is the POST-REMOVAL sibling list, so a valid
    `position` is `[0, len(others)]` (matching place_node)."""
    others = list(
        Element.objects.select_for_update()
        .filter(unit=unit)
        .exclude(pk=element.pk)
        .order_by("order", "pk")
    )
    if position is None or position > len(others):
        position = len(others)
    if position < 0:
        position = 0
    ordered = others[:position] + [element] + others[position:]
    changed = False
    for idx, el in enumerate(ordered):
        if el.order != idx:
            el.order = idx
            el.save(update_fields=["order"])
            changed = True
    return changed


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


# --- per-course structure presets + builder "+" affordances -----------------
# The model stores three booleans (uses_parts/uses_chapters/uses_sections);
# presets are a UI-layer naming over flag-triples. `unit` is always present
# (mandatory leaf) and has no flag. A child's kind must be strictly deeper
# (larger RANK) than its parent's; the top scope (parent_kind=None) allows all
# kinds, then everything is intersected with the course's allowed set.
PRESET_FLAGS = {
    "flat": (False, False, False),  # course -> unit
    "chapters": (False, True, False),  # course -> chapter -> unit
    "parts": (True, True, False),  # course -> part -> chapter -> unit
    "full": (True, True, True),  # course -> part -> chapter -> section -> unit
}


def kinds_for_flags(parts, chapters, sections):
    """Allowed kinds in RANK order for the given optional-level flags. Always
    ends with 'unit' (the mandatory leaf)."""
    ks = []
    if parts:
        ks.append("part")
    if chapters:
        ks.append("chapter")
    if sections:
        ks.append("section")
    ks.append("unit")
    return ks


def kinds_for_preset(key):
    """Allowed kinds for a named preset key (see PRESET_FLAGS)."""
    return kinds_for_flags(*PRESET_FLAGS[key])


def preset_for_flags(parts, chapters, sections):
    """Reverse lookup: the preset key matching a flag-triple, else None (Custom)."""
    target = (parts, chapters, sections)
    for key, flags in PRESET_FLAGS.items():
        if flags == target:
            return key
    return None


def legal_child_kinds(parent_kind, allowed_kinds):
    """Kinds a node of `parent_kind` (a kind string, or None for the top scope)
    may directly contain, in RANK order, restricted to this course's
    `allowed_kinds` (the per-course structure policy)."""
    order = sorted(ContentNode.RANK, key=ContentNode.RANK.get)
    if parent_kind is None:
        deeper = order
    else:
        parent_rank = ContentNode.RANK[parent_kind]
        deeper = [k for k in order if ContentNode.RANK[k] > parent_rank]
    return [k for k in deeper if k in allowed_kinds]


def primary_child_kind(parent_kind, allowed_kinds):
    """One-click primary "+" kind for a scope with >=3 legal child kinds:
    'chapter' when chapter is legal here (preserves today's UX), else the
    shallowest legal kind. None when <3 legal kinds (all chips show inline)."""
    legal = legal_child_kinds(parent_kind, allowed_kinds)
    if len(legal) < 3:
        return None
    if "chapter" in legal:
        return "chapter"
    return legal[0]
