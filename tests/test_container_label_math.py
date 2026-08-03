"""A container's LABEL is content too: tab labels and a spoiler's toggle label are
authored text that may carry inline math, and both are already inside the scopes
`math.js` typesets (`.el--tabs`, `.spoiler__toggle`). But KaTeX only ships when the
lesson/quiz context says `has_math`, and that detection walked a container's
CHILDREN only -- so a unit whose sole math lives in a label rendered raw `\\(x^2\\)`
with the vendor scripts never loaded.

Every test here is isolated on purpose: the label is the ONLY math in the unit, and
the child carries none. A unit with math anywhere else passes whether or not the
label is inspected.
"""

import pytest

from courses.models import Element
from courses.models import SpoilerElement
from courses.models import TabsElement
from courses.models import TextElement
from courses.views import build_lesson_context
from tests.factories import make_course_with_unit
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db

NO_MATH = "<p>plain prose, no delimiters</p>"


def test_has_math_sees_math_in_a_tab_label():
    """Mutant: drop the label clause from `_tabs_has_math` -> has_math is False and
    the lesson ships the raw LaTeX source in the tab strip."""
    _course, unit = make_course_with_unit()
    user = make_verified_user(username="tab_label_math")
    tabs = TabsElement.objects.create(
        data={
            "tabs": [
                {"id": "t000001", "label": r"Wzór \(x^2\)"},
                {"id": "t000002", "label": "Plain"},
            ]
        }
    )
    join = Element.objects.create(unit=unit, content_object=tabs)
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body=NO_MATH),
        parent=join,
        tab_id="t000001",
    )

    ctx = build_lesson_context(unit, user)

    assert ctx["has_math"] is True


def test_has_math_sees_math_in_a_spoiler_label():
    """Mutant: drop the label clause from `_spoiler_has_math`. The nestable spoiler
    has an EMPTY body, so its children were the only thing inspected."""
    _course, unit = make_course_with_unit()
    user = make_verified_user(username="spoiler_label_math")
    spoiler = SpoilerElement.objects.create(label=r"Dowód \(a<b\)", body="")
    join = Element.objects.create(unit=unit, content_object=spoiler)
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body=NO_MATH),
        parent=join,
        tab_id=SpoilerElement.SLOT_ID,
    )

    ctx = build_lesson_context(unit, user)

    assert ctx["has_math"] is True
