"""paste_allowed and resolve_scope must agree for a childless element.

They are two implementations of the same containment question reached from
different namespaces, and nothing else pins them together.
"""

import pytest

from courses import builder
from courses.models import CalloutElement
from courses.models import Element
from courses.models import MarkDoneElement
from courses.models import RevealGateElement
from courses.models import TabsElement
from courses.models import TextElement
from courses.models import TwoColumnElement
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db


def _tabs_at(unit, parent=None, tab=""):
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(
        unit=unit, content_object=obj, parent=parent, tab_id=tab
    )
    return join, [t["id"] for t in obj.data["tabs"]]


# (form key as element_add sends it, factory for the concrete).
#
# Rows 1-2 (text, tabs) have IDENTICAL form and transfer keys.
# Rows 3-5 (twocolumn -> two_column, markdone -> mark_done, revealgate ->
#   reveal_gate) are ALIASED, and are the only rows that can catch a broken alias
#   entry. All three concretes construct with no arguments, which is why they were
#   chosen over the more elaborate question types.
# Row 6 (callout) is NOT aliased -- it is here for the container-cap seam #214
#   moved: it is the only case where both rules must agree that a single-slot
#   container's ceiling is 3 rather than 4.
CASES = [
    ("text", lambda: TextElement.objects.create(body="<p>t</p>")),
    ("tabs", lambda: TabsElement.objects.create(data=TabsElement.default_data())),
    (
        "twocolumn",
        lambda: TwoColumnElement.objects.create(data=TwoColumnElement.default_data()),
    ),
    ("markdone", lambda: MarkDoneElement.objects.create()),
    ("revealgate", lambda: RevealGateElement.objects.create()),
    # A CONTAINER as of #214, and the only row that exercises the container cap on
    # both sides: resolve_scope decides "is this a container?" from
    # CONTAINER_TRANSFER_KEYS, paste_allowed from _slot_cap's registry lookup. #214
    # flipped callout in BOTH structures; nothing else here proves they agree about
    # its depth ceiling. Admissible at parent_depth 1-2, refused at 3.
    ("callout", lambda: CalloutElement.objects.create()),
]


def _resolve_ok(unit, dest, slot, form_key):
    try:
        builder.resolve_scope(unit, str(dest.pk), slot, form_key)
        return True
    except builder.NestingError:
        return False


@pytest.mark.parametrize("form_key,make", CASES, ids=[c[0] for c in CASES])
@pytest.mark.parametrize("parent_depth", [1, 2, 3])
def test_the_two_rules_agree_for_a_childless_element(form_key, make, parent_depth):
    """Mutant: break one _NESTABLE_FORM_KEY_ALIASES entry -> the aliased rows go
    RED while text and tabs stay green."""
    _course, unit = make_course_with_unit()

    dest, slots = _tabs_at(unit)
    for _hop in range(parent_depth - 1):
        dest, slots = _tabs_at(unit, parent=dest, tab=slots[0])

    # A row distinct from the destination and neither its ancestor nor its
    # descendant, so clauses 4 and 5 -- which have no resolve_scope counterpart --
    # cannot fire and produce a false RED.
    subject = Element.objects.create(unit=unit, content_object=make())

    allowed, _reason = builder.paste_allowed(unit, subject, dest, slots[0], "move")

    assert allowed == _resolve_ok(unit, dest, slots[0], form_key)


@pytest.mark.parametrize("form_key,make", CASES, ids=[c[0] for c in CASES])
def test_the_two_rules_agree_at_the_unconstructible_parent_depth(form_key, make):
    """Parent depth 4 cannot be reached by any legal write -- a parent must be a
    container, and cap says a container never lives at depth 4. Built by direct ORM
    write precisely to prove both rules reject it identically; the normal add path
    could never produce this row.
    """
    _course, unit = make_course_with_unit()

    dest, slots = _tabs_at(unit)
    for _hop in range(3):
        dest, slots = _tabs_at(unit, parent=dest, tab=slots[0])
    assert builder.element_depth(dest) == 4

    subject = Element.objects.create(unit=unit, content_object=make())

    allowed, _reason = builder.paste_allowed(unit, subject, dest, slots[0], "move")

    assert allowed is False
    assert _resolve_ok(unit, dest, slots[0], form_key) is False
