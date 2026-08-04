"""CalloutElement as a single-slot container (mirrors SpoilerElement)."""

import pytest

from courses.models import SINGLE_SLOT_ID
from courses.models import CalloutElement
from courses.models import Element
from courses.models import TextElement
from tests.factories import add_element
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db


def _callout_with_children(unit, bodies, callout_body=""):
    co = CalloutElement.objects.create(kind="example", body=callout_body)
    join = add_element(unit, co)
    for i, b in enumerate(bodies):
        Element.objects.create(
            unit=unit,
            content_object=TextElement.objects.create(body=b),
            parent=join,
            tab_id=SINGLE_SLOT_ID,
            order=i,
        )
    return co, join


def test_callout_does_not_respell_the_slot_literal():
    """The REAL pin. `CalloutElement.SLOT_ID is SINGLE_SLOT_ID` is VACUOUS: "only" is
    identifier-shaped, so CPython interns it and an independent `SLOT_ID = "only"`
    yields the SAME object -- green under exactly the divergence it would guard.
    Task 1 scans SpoilerElement; the spec's row says NEITHER model may re-spell it.
    """
    from courses.tests.test_single_slot_constant import _executable_source

    src = _executable_source(CalloutElement)
    assert "SLOT_ID" in src
    assert '"only"' not in src
    assert "'only'" not in src


def test_resolved_children_is_empty_when_join_row_is_transient():
    co = CalloutElement.objects.create(kind="example", body="<p>x</p>")
    assert co.resolved_children() == []


def test_render_emits_children_in_order():
    _course, unit = make_course_with_unit()
    co, join = _callout_with_children(unit, ("<p>FIRST</p>", "<p>SECOND</p>"))
    html = co.render(element=join, state={}, slug="x", node_pk=unit.pk)
    assert "callout__children" in html
    assert html.index("FIRST") < html.index("SECOND")


def test_render_emits_body_ABOVE_children():
    _course, unit = make_course_with_unit()
    co, join = _callout_with_children(
        unit, ("<p>CHILD</p>",), callout_body="<p>BODY</p>"
    )
    html = co.render(element=join, state={}, slug="x", node_pk=unit.pk)
    # Source ORDER, not mere presence -- a presence-only assertion is green under
    # the wrong order.
    assert html.index("BODY") < html.index("CHILD")


def test_render_passes_element_state_not_state():
    """The recursive {% render_element child %} reads context["element_state"].

    Passing `state=state` (matching the kwarg name) renders nested stateful children
    with empty state and an empty save URL -- a silent, 200-OK state loss.

    The child MUST be genuinely stateful: a TextElement has no blob and no save URL,
    so `state=` vs `element_state=` changes nothing observable and the test is vacuous.
    And no `or` -- each assertion must carry on its own.
    """
    from courses.models import StepperElement
    from courses.models import StepperStep

    _course, unit = make_course_with_unit()
    co = CalloutElement.objects.create(kind="example")
    join = add_element(unit, co)
    st = StepperElement.objects.create(prompt="p")
    StepperStep.objects.create(stepper=st, content="one", order=0)
    StepperStep.objects.create(stepper=st, content="two", order=1)
    child = Element.objects.create(
        unit=unit, content_object=st, parent=join, tab_id=CalloutElement.SLOT_ID
    )
    html = co.render(
        element=join,
        state={child.pk: {"shown": 2}},
        slug="course-slug",
        node_pk=unit.pk,
    )
    assert "shown" in html and "2" in html  # the stored blob reached the child
    assert "course-slug" in html  # the save URL is populated
