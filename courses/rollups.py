from courses.models import ContentNode
from courses.models import UnitProgress


def quiz_units_in_order(course):
    """Quiz units (kind=UNIT, unit_type=QUIZ) in depth-first pre-order of the content
    tree — the order they appear walking the outline top to bottom. ONE query
    (course.nodes.all(), ordered by ContentNode.Meta.ordering = ["order","pk"]);
    parent_id-grouped recursion. A flat iteration of course.nodes.all() is NOT
    pre-order (sibling `order` is only locally monotonic) and must not be used.
    """
    nodes = list(course.nodes.all())
    children = {}
    for node in nodes:
        children.setdefault(node.parent_id, []).append(node)

    result = []

    def walk(parent_id):
        for node in children.get(parent_id, []):
            if (
                node.kind == ContentNode.Kind.UNIT
                and node.unit_type == ContentNode.UnitType.QUIZ
            ):
                result.append(node)
            walk(node.pk)

    walk(None)
    return result


def build_outline(course, user):
    """Return a nested list of node dicts with required/additional rollups.

    Two queries (nodes + the user's completed unit ids). `required` counts only
    obligatory lesson units; `additional_done` counts completed non-obligatory lesson
    units; quiz units are excluded from both (uncompletable in 1a).
    """
    nodes = list(course.nodes.all())
    children = {}
    for node in nodes:
        children.setdefault(node.parent_id, []).append(node)

    completed = set()
    if user.is_authenticated:
        completed = set(
            UnitProgress.objects.filter(
                student=user, unit__course=course, completed=True
            ).values_list("unit_id", flat=True)
        )

    def build(node):
        kids = [build(child) for child in children.get(node.pk, [])]
        if node.kind == ContentNode.Kind.UNIT:
            is_lesson = node.unit_type == ContentNode.UnitType.LESSON
            required_total = 1 if (is_lesson and node.obligatory) else 0
            required_done = 1 if (required_total and node.pk in completed) else 0
            additional_done = (
                1 if (is_lesson and not node.obligatory and node.pk in completed) else 0
            )
        else:
            required_total = sum(k["required_total"] for k in kids)
            required_done = sum(k["required_done"] for k in kids)
            additional_done = sum(k["additional_done"] for k in kids)
        return {
            "node": node,
            "children": kids,
            "required_total": required_total,
            "required_done": required_done,
            "additional_done": additional_done,
            "is_unit": node.kind == ContentNode.Kind.UNIT,
            "completed": node.kind == ContentNode.Kind.UNIT and node.pk in completed,
        }

    return [build(node) for node in children.get(None, [])]
