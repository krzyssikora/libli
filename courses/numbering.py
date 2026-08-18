"""Consecutive numbering of callouts within a unit.

ONE public function. It is deliberately self-contained -- it re-queries its own
roots rather than accepting a caller's element list -- so its query count is a
property of this module and not of each of its four call sites.

See docs/superpowers/specs/2026-08-18-callout-numbering-design.md section 3.
"""

from courses.models import BeforeAfterElement
from courses.models import CalloutElement
from courses.models import Element
from courses.models import SpoilerElement
from courses.models import TabsElement
from courses.models import TwoColumnElement


def _children_of(obj):
    return obj.resolved_children()


def _tab_children_of(obj):
    return [child for _tab, children in obj.resolved_tabs() for child in children]


def _column_children_of(obj):
    return [child for _col, children in obj.resolved_columns() for child in children]


def _slot_children_of(obj):
    return [child for _slot, children in obj.resolved_slots() for child in children]


# The accessor per container type. Keyed by model class; an entry MUST exist for
# every member of builder.CONTAINER_MODELS (pinned by test_accessors_cover_every_
# container). Descending through the containers' OWN accessors is the whole design:
# document order is NOT order_by("order", "pk") -- tab children interleave in `order`
# -- and re-deriving the grouping here would be a second implementation of reading
# order that drifts from the render the first time a container changes.
#
# Inheriting the accessors inherits their quirks, which is the point:
#   - resolved_tabs SKIPS a child whose tab_id matches no tab
#   - resolved_slots APPENDS an unknown-tab_id child to the `before` bucket
#   - resolved_columns applies the destructive 2..4 render clamp
# In each case the render drops or keeps exactly what the numbering does.
ACCESSORS = {
    SpoilerElement: _children_of,
    CalloutElement: _children_of,
    TabsElement: _tab_children_of,
    TwoColumnElement: _column_children_of,
    BeforeAfterElement: _slot_children_of,
}


def callout_numbers(node):
    """{Element.pk: number} for every numbered callout in `node`, in document order.

    `node` is a unit ContentNode. A node with no callouts returns {}.
    """
    from courses import builder  # module attribute, never a module-level from-import

    # Early-out: most units have no callout at all, and the call is unconditional at
    # all four context sites. Filters on content_type__model rather than resolving a
    # ContentType object, so it never consults the process-wide ContentType cache and
    # the pinned query count cannot depend on cache warmth. `app_label` is required:
    # Element.content_type's limit_choices_to is a form/admin constraint, not a
    # database one. Unit-wide, NOT parent__isnull=True -- a unit whose only callout is
    # nested must NOT be short-circuited.
    if not Element.objects.filter(
        unit=node,
        content_type__app_label="courses",
        content_type__model="calloutelement",
    ).exists():
        return {}

    counter = 0
    numbers = {}
    seen = set()

    def walk(rows):
        nonlocal counter
        for row in rows:
            if row.pk in seen:
                continue
            seen.add(row.pk)
            obj = row.content_object
            if obj is None:
                continue  # dangling GFK: skipped, not counted, not an error
            if isinstance(obj, CalloutElement) and obj.numbered:
                counter += 1
                numbers[row.pk] = counter  # PRE-ORDER: before descending
            if type(obj) in builder.CONTAINER_MODELS:
                try:
                    accessor = ACCESSORS[type(obj)]
                except KeyError:
                    raise RuntimeError(
                        f"no accessor for container {type(obj).__name__}"
                    ) from None
                walk(accessor(obj))

    walk(
        node.elements.filter(parent__isnull=True)
        .order_by("order", "pk")
        .select_related("content_type")
        .prefetch_related("content_object")
    )
    return numbers
