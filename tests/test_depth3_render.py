"""Task 7: depth-3 characterization -- `has_math` detection and the student render.

No production change. `_element_has_math`/`_tabs_has_math` already recurse and the
render path (`{% render_element %}` in tabselement.html/spoilerelement.html) already
walks into nested children -- these tests pin that existing behaviour at the new
depth-3 shape the nesting-cap lift makes reachable.
"""

import pytest
from django.urls import reverse

from courses import builder
from courses.models import Element
from courses.models import MathElement
from courses.models import SpoilerElement
from courses.models import TextElement
from courses.tests.test_nesting_rule import _mk
from courses.views import build_lesson_context
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import make_course_with_unit
from tests.factories import make_login
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db


def _assert_isolated(unit, math_join):
    """Machine-checked isolation: within THIS unit, exactly one Element resolves
    to a MathElement, it is the depth-3 leaf (not a top-level or shallow sibling),
    and the unit's only top-level element is the tabs container -- never math
    itself. A unit that also carried top-level (or depth-1/2) math would pass
    `has_math` regardless of whether the tabs recursion works, making the test
    vacuous."""
    math_joins = [
        e
        for e in unit.elements.all().prefetch_related("content_object")
        if isinstance(e.content_object, MathElement)
    ]
    assert math_joins == [math_join]
    assert builder.element_depth(math_join) == 3
    top_level = list(unit.elements.filter(parent__isnull=True))
    assert len(top_level) == 1
    assert not isinstance(top_level[0].content_object, MathElement)


def test_has_math_detects_math_at_depth_3():
    """Pinned chain: tabs > spoiler > math, with NO other math in the unit.
    Isolation is mandatory -- a unit with top-level math passes either way."""
    _course, unit = make_course_with_unit()
    user = make_verified_user(username="depth3_math")

    top = _mk(unit, "tabs")
    tab_id = top.content_object.data["tabs"][0]["id"]
    sp = _mk(unit, "spoiler", parent=top, tab=tab_id)
    math_join = _mk(unit, "math", parent=sp, tab=SpoilerElement.SLOT_ID)

    _assert_isolated(unit, math_join)

    ctx = build_lesson_context(unit, user)
    assert ctx["has_math"] is True


def test_depth_3_leaf_renders_inside_its_nested_container(client):
    """EXEMPT from the mutant rule, deliberately: the render path is unchanged by
    this slice, so this is a characterization test pinning existing behaviour at a
    new depth, not a test of new logic."""
    user = make_login(client, "depth3_render")
    course = CourseFactory(slug="d3render")
    EnrollmentFactory(student=user, course=course)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None
    )

    top = _mk(unit, "tabs")
    tab_id = top.content_object.data["tabs"][0]["id"]
    sp = _mk(unit, "spoiler", parent=top, tab=tab_id)

    marker = "DEPTH3-LEAF-MARKER-9f31"
    leaf_obj = TextElement.objects.create(body=f"<p>{marker}</p>")
    leaf_join = Element.objects.create(
        unit=unit,
        content_object=leaf_obj,
        parent=sp,
        tab_id=SpoilerElement.SLOT_ID,
        order=0,
    )
    assert builder.element_depth(leaf_join) == 3

    resp = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    )
    assert resp.status_code == 200
    assert marker in resp.content.decode()
