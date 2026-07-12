import pytest
from django.contrib.contenttypes.models import ContentType

from courses.models import Element
from courses.models import FillGateElement
from courses.models import TabsElement
from courses.views import build_lesson_context


def _add_fillgate(unit, stem, answers):
    el = FillGateElement.objects.create(stem=stem, answers=answers)
    Element.objects.create(
        unit=unit,
        content_type=ContentType.objects.get_for_model(FillGateElement),
        object_id=el.pk,
    )
    return el


@pytest.fixture
def lesson_unit_node():
    from tests.factories import make_course_with_unit

    _course, unit = make_course_with_unit()
    return unit


@pytest.fixture
def student_user():
    from tests.factories import make_verified_user

    return make_verified_user(username="student_ctx")


@pytest.fixture
def tab_child_factory():
    """Attach `child_obj` as a child of a (freshly created) TabsElement living in
    `unit` -- mirrors lesson_with_tab_gate in test_reveal_gate_view_flag.py."""

    def _make(unit, child_obj):
        tabs_obj = TabsElement.objects.create(data=TabsElement.default_data())
        join = Element.objects.create(unit=unit, content_object=tabs_obj)
        tab_id = tabs_obj.data["tabs"][0]["id"]
        return Element.objects.create(
            unit=unit,
            content_object=child_obj,
            parent=join,
            tab_id=tab_id,
        )

    return _make


@pytest.mark.django_db
def test_fillgate_arms_flags(lesson_unit_node, student_user):
    unit = lesson_unit_node
    _add_fillgate(unit, "plain ￿0￿", [["a"]])
    ctx = build_lesson_context(unit, student_user)
    assert ctx["has_reveal_gate"] is True  # arms pre-hide + reveal.js
    assert ctx["has_fill_gate"] is True  # gates fillgate.js
    assert ctx["has_math"] is False


@pytest.mark.django_db
def test_fillgate_math_detected_top_level(lesson_unit_node, student_user):
    unit = lesson_unit_node
    _add_fillgate(unit, r"\(x^2\) = ￿0￿", [["4"]])
    ctx = build_lesson_context(unit, student_user)
    assert ctx["has_math"] is True


@pytest.mark.django_db
def test_fillgate_math_detected_nested_in_tab(
    lesson_unit_node, student_user, tab_child_factory
):
    # MANDATORY (spec Math-detection): a fill-gate nested in a tab whose stem has math
    # must set has_math via _element_has_math (the tabs recursion), not the top-level
    # chain.
    unit = lesson_unit_node
    fg = FillGateElement.objects.create(stem=r"\(y\) = ￿0￿", answers=[["1"]])
    tab_child_factory(unit, fg)  # attach fg as a child of a TabsElement in this unit
    ctx = build_lesson_context(unit, student_user)
    assert ctx["has_math"] is True
