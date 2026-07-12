import pytest
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from courses.models import Element
from courses.models import SwitchGateElement
from courses.models import TabsElement
from courses.switchgate import SENTINEL_TOKEN
from courses.views import build_lesson_context

pytestmark = pytest.mark.django_db


def _add_switchgate(unit, stem, options, answer=0):
    el = SwitchGateElement.objects.create(
        stem=stem, options=list(options), answer=answer
    )
    Element.objects.create(
        unit=unit,
        content_type=ContentType.objects.get_for_model(SwitchGateElement),
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

    return make_verified_user(username="student_ctx_sg")


@pytest.fixture
def tab_child_factory():
    """Attach `child_obj` as a child of a (freshly created) TabsElement living in
    `unit` -- mirrors tab_child_factory in test_fillgate_context.py."""

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


def test_switchgate_arms_flags(lesson_unit_node, student_user):
    unit = lesson_unit_node
    _add_switchgate(unit, f"plain {SENTINEL_TOKEN}", ["a", "b"])
    ctx = build_lesson_context(unit, student_user)
    assert ctx["has_reveal_gate"] is True  # arms pre-hide + reveal.js
    assert ctx["has_switch_gate"] is True  # gates switchgate.js
    assert ctx["has_math"] is False


def test_switchgate_math_in_option_detected_top_level(lesson_unit_node, student_user):
    unit = lesson_unit_node
    _add_switchgate(unit, f"plain {SENTINEL_TOKEN}", [r"\(x\)", "b"])
    ctx = build_lesson_context(unit, student_user)
    assert ctx["has_math"] is True


def test_switchgate_math_in_stem_detected_top_level(lesson_unit_node, student_user):
    unit = lesson_unit_node
    _add_switchgate(unit, rf"\(y\) {SENTINEL_TOKEN}", ["a", "b"])
    ctx = build_lesson_context(unit, student_user)
    assert ctx["has_math"] is True


def test_switchgate_math_detected_nested_in_tab(
    lesson_unit_node, student_user, tab_child_factory
):
    # MANDATORY (spec Math-detection): a switch-gate nested in a tab whose OPTION has
    # math must set has_math via _element_has_math (the tabs recursion), not the
    # top-level chain.
    unit = lesson_unit_node
    sg = SwitchGateElement.objects.create(
        stem=SENTINEL_TOKEN, options=[r"\(z\)", "b"], answer=0
    )
    tab_child_factory(unit, sg)  # attach sg as a child of a TabsElement in this unit
    # Guard: fail loudly if the switchgate isn't actually nested, so the test
    # can't pass vacuously when seeding is wrong.
    assert SwitchGateElement.objects.filter(options__contains=[r"\(z\)"]).exists()
    ctx = build_lesson_context(unit, student_user)
    assert ctx["has_math"] is True


@pytest.fixture
def enrolled_unit():
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    course = CourseFactory()
    return ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None
    )


@pytest.fixture
def enrolled_client(client, enrolled_unit):
    from tests.factories import EnrollmentFactory
    from tests.factories import make_login

    user = make_login(client, "switchgate-ctx-student")
    EnrollmentFactory(student=user, course=enrolled_unit.course)
    return client


def _lesson_url(unit):
    return reverse("courses:lesson_unit", args=[unit.course.slug, unit.pk])


def test_switchgate_arms_reveal_and_script(enrolled_client, enrolled_unit):
    _add_switchgate(enrolled_unit, f"x {SENTINEL_TOKEN} y", ["a", "b"])
    body = enrolled_client.get(_lesson_url(enrolled_unit)).content.decode()
    assert "reveal-armed" in body  # pre-hide armed
    assert "switchgate.js" in body  # script loaded
    assert "__switchGateBooted" in body  # watchdog registered


def test_no_switchgate_script_without_gate(enrolled_client, enrolled_unit):
    body = enrolled_client.get(_lesson_url(enrolled_unit)).content.decode()
    assert "switchgate.js" not in body
    assert "__switchGateBooted" not in body
